"""The CLgen language model."""
import os
import pathlib
import typing

import humanize
import numpy as np
from absl import flags
from absl import logging

from deeplearning.clgen import cache
from deeplearning.clgen import errors
from deeplearning.clgen import samplers
from deeplearning.clgen import telemetry
from deeplearning.clgen.corpuses import atomizers
from deeplearning.clgen.corpuses import corpuses
from deeplearning.clgen.models import builders
from deeplearning.clgen.models import keras_backend
from deeplearning.clgen.models import tensorflow_backend
from deeplearning.clgen.proto import internal_pb2
from deeplearning.clgen.proto import model_pb2
from deeplearning.clgen.proto import telemetry_pb2
from labm8 import crypto
from labm8 import labdate
from labm8 import lockfile
from labm8 import logutil
from labm8 import pbutil


FLAGS = flags.FLAGS

flags.DEFINE_bool(
    'experimental_batched_sampling', False,
    'Enable an experimental batched sampling feature. THIS FEATURE IS STILL '
    'EXPERIMENTAL AND HAS NOT BEEN THOROUGHLY REVIEWED OR UNDERSTOOD.')


class Model(object):
  """A CLgen language model.

  Please note model instances should be treated as immutable. Upon
  instantiation, a model's properties are used to determine its hash. If you
  modify a property after instantiation, the hash will be out of date, which
  can lead to bad things happening.
  """

  def __init__(self, config: model_pb2.Model):
    """Instantiate a model.

    Args:
      config: A Model message.

    Raises:
      TypeError: If the config argument is not a Model proto.
      UserError: In case on an invalid config.
    """
    # Error early, so that a cache isn't created.
    if not isinstance(config, model_pb2.Model):
      t = type(config).__name__
      raise TypeError(f"Config must be a Model proto. Received: '{t}'")
    # Validate config options.
    if config.training.sequence_length < 1:
      raise errors.UserError('TrainingOptions.sequence_length must be >= 1')

    self.config = model_pb2.Model()
    self.config.CopyFrom(builders.AssertIsBuildable(config))
    self.corpus = corpuses.Corpus(config.corpus)
    self.hash = self._ComputeHash(self.corpus, self.config)
    self.cache = cache.mkcache('model', self.hash)
    # Create the necessary cache directories.
    (self.cache.path / 'checkpoints').mkdir(exist_ok=True)
    (self.cache.path / 'samples').mkdir(exist_ok=True)
    (self.cache.path / 'logs').mkdir(exist_ok=True)

    # Create symlink to encoded corpus.
    symlink = self.cache.path / 'corpus'
    if not symlink.is_symlink():
      os.symlink(os.path.relpath(
          pathlib.Path(self.corpus.encoded.url[len('sqlite:///'):]).parent,
          self.cache.path), symlink)

    # Create symlink to the atomizer.
    symlink = self.cache.path / 'atomizer'
    if not symlink.is_symlink():
      os.symlink(
          os.path.relpath(self.corpus.atomizer_path, self.cache.path), symlink)

    # Validate metadata against cache.
    if self.cache.get('META.pbtxt'):
      cached_meta = pbutil.FromFile(pathlib.Path(self.cache['META.pbtxt']),
                                    internal_pb2.ModelMeta())
      # Exclude num_epochs and corpus location from metadata comparison.
      config_to_compare = model_pb2.Model()
      config_to_compare.CopyFrom(self.config)
      config_to_compare.corpus.ClearField('contentfiles')
      config_to_compare.training.ClearField('num_epochs')
      # These fields should have already been cleared, but we'll do it again
      # so that metadata comparisons don't fail when the cached meta schema
      # is updated.
      cached_to_compare = model_pb2.Model()
      cached_to_compare.CopyFrom(cached_meta.config)
      cached_to_compare.corpus.ClearField('contentfiles')
      cached_to_compare.training.ClearField('num_epochs')
      if config_to_compare != cached_to_compare:
        raise errors.InternalError('Metadata mismatch')
      self.meta = cached_meta
    else:
      self.meta = internal_pb2.ModelMeta()
      self.meta.config.CopyFrom(self.config)
      self._WriteMetafile()

    self.backend = {
      model_pb2.NetworkArchitecture.TENSORFLOW: tensorflow_backend.TensorFlowBackend,
      model_pb2.NetworkArchitecture.KERAS: keras_backend.KerasBackend,
    }[config.architecture.backend](self.config, self.cache, self.corpus)

  @staticmethod
  def _ComputeHash(corpus_: corpuses.Corpus, config: model_pb2.Model) -> str:
    """Compute model hash.

    The hash is computed from the ID of the corpus and the serialized
    representation of the config proto. The number of epochs that the model is
    trained for does not affect the hash, since we can share checkpoints
    between different models if the only variable is the epoch count. E.g.
    we have a model trained for 10 epochs, we can use the checkpoint as the
    starting point for a training a model for 20 epochs.

    Args:
      corpus: A corpus instance.
      config: A Model config proto.

    Returns:
      The unique model ID.
    """
    config_to_hash = model_pb2.Model()
    config_to_hash.CopyFrom(config)
    config_to_hash.ClearField('corpus')
    config_to_hash.training.ClearField('num_epochs')
    return crypto.sha1_list(corpus_.hash,
                            config_to_hash.SerializeToString())

  def Train(self) -> 'Model':
    """Train the model.

    Returns:
      The model instance.

    Raises:
      UnableToAcquireLockError: If the model is locked (i.e. there is another
        process currently modifying the model).
    """
    self.corpus.Create()
    with self.training_lock.acquire():
      self.backend.Train(self.corpus)
    total_time_ms = sum(
        t.epoch_wall_time_ms
        for t in self.TrainingTelemetry()[:self.config.training.num_epochs])
    logging.info('Trained model for %d epochs in %s ms (%s).',
                 self.config.training.num_epochs,
                 humanize.intcomma(total_time_ms),
                 humanize.naturaldelta(total_time_ms / 1000))
    return self

  def Sample(
      self, sampler: samplers.Sampler, min_num_samples: int,
      seed: int = None) -> typing.List[model_pb2.Sample]:
    """Sample a model.

    If the model is not already trained, calling Sample() first trains the
    model. Thus a call to Sample() is equivalent to calling Train() then
    Sample().

    Args:
      sampler: The sampler to sample using.
      min_num_samples: The minimum number of samples to return. Note that the
        true number of samples returned may be higher than this value, as
        sampling occurs in batches. The model will continue producing samples
        until the lowest mulitple of the sampler batch size property that is
        larger than this value. E.g. if min_num_samples is 7 and the Sampler
        batch size is 10, 10 samples will be returned.
      seed: A numeric value to seed the RNG with. If not present, the RNG is
        seeded randomly.

    Returns:
      A list of Sample protos.

    Raises:
      UnableToAcquireLockError: If the model is locked (i.e. there is another
        process currently modifying the model).
      InvalidStartText: If the sampler start text cannot be encoded.
      InvalidSymtokTokens: If the sampler symmetrical depth tokens cannot be
        encoded.
    """
    self.Train()

    sample_count = 1
    self.SamplerCache(sampler).mkdir(exist_ok=True)
    with logutil.TeeLogsToFile(
        f'sampler_{sampler.hash}', self.cache.path / 'logs'):
      logging.info("Sampling: '%s'", sampler.start_text)
      if min_num_samples < 0:
        logging.warning(
            'Entering an infinite sample loop, this process will never end!')
      sample_start_time = labdate.MillisecondsTimestamp()

      atomizer = self.corpus.atomizer
      sampler.Specialize(atomizer)
      batch_size = self.backend.InitSampling(sampler, seed)

      samples = []
      sample_dir = self.SamplerCache(sampler)

      # Per-sample batch outer loop. Continues until we have as many samples
      # as we want.
      while True:
        samples_in_progress = [
          sampler.tokenized_start_text.copy()
          for _ in range(batch_size)]
        done = np.zeros(batch_size, dtype=np.bool)
        start_time = labdate.MillisecondsTimestamp()
        wall_time_start = start_time

        self.backend.InitSampleBatch(sampler, batch_size)

        # Sampling loop. Continues until all samples in the batch are done.
        while True:
          indices = self.backend.SampleNextIndices(sampler, batch_size)

          # Iterate over all samples in batch to determine whether they're
          # done.
          for i in range(batch_size):
            if done[i]:
              continue

            token = atomizer.decoder[indices[i]]
            samples_in_progress[i].append(token)
            if sampler.SampleIsComplete(samples_in_progress[i]):
              end_time = labdate.MillisecondsTimestamp()
              done[i] = 1
              sample = model_pb2.Sample(
                  text=''.join(samples_in_progress[i]),
                  sample_start_epoch_ms_utc=start_time,
                  sample_time_ms=end_time - start_time,
                  wall_time_ms=end_time - wall_time_start,
                  num_tokens=len(samples_in_progress[i]))
              print(f'=== BEGIN CLGEN SAMPLE {sample_count} '
                    f'===\n\n{sample.text}\n')
              sample_count += 1
              sample_id = crypto.sha256_str(sample.text)
              sample_path = sample_dir / f'{sample_id}.pbtxt'
              pbutil.ToFile(sample, sample_path)
              if min_num_samples > 0:
                samples.append(sample)
              wall_time_start = labdate.MillisecondsTimestamp()

          # Complete the batch.
          if done.all():
            break

        # Complete sampling. Note that sample_count starts at 1.
        if sample_count > min_num_samples:
          now = labdate.MillisecondsTimestamp()
          logging.info(
              'Produced %s samples at a rate of %s ms / sample.',
              humanize.intcomma(len(samples)),
              humanize.intcomma(
                  int((now - sample_start_time) / max(len(samples), 1))))
          break

    return samples

  def SampleFast(
      self, sampler: samplers.Sampler, min_num_samples: int,
      seed: int = None) -> typing.List[model_pb2.Sample]:
    """Sample a model.

    Same as Sample(), but without printing or caching samples. Because samples
    are not cached, infinite sampling loops are not supported, since we must
    return the sample protos at some point.

    Args:
      sampler: The sampler to sample using.
      min_num_samples: The minimum number of samples to return. Note that the
        true number of samples returned may be higher than this value, as
        sampling occurs in batches. The model will continue producing samples
        until the lowest mulitple of the sampler batch size property that is
        larger than this value. E.g. if min_num_samples is 7 and the Sampler
        batch size is 10, 10 samples will be returned.
      seed: A numeric value to seed the RNG with. If not present, the RNG is
        seeded randomly.

    Returns:
      A list of Sample protos.

    Raises:
      UnableToAcquireLockError: If the model is locked (i.e. there is another
        process currently modifying the model).
      InvalidStartText: If the sampler start text cannot be encoded.
      InvalidSymtokTokens: If the sampler symmetrical depth tokens cannot be
        encoded.
    """
    self.Train()

    sample_count = 1
    with logutil.TeeLogsToFile(
        f'sampler_{sampler.hash}', self.cache.path / 'logs'):
      logging.info("Sampling: '%s'", sampler.start_text)
      sample_start_time = labdate.MillisecondsTimestamp()
      atomizer = self.corpus.atomizer
      sampler.Specialize(atomizer)
      batch_size = self.backend.InitSampling(sampler, seed)
      samples = []

      # Per-sample batch outer loop. Continues until we have as many samples
      # as we want.
      while True:
        samples_in_progress = [
          sampler.tokenized_start_text.copy()
          for _ in range(batch_size)]
        done = np.zeros(batch_size, dtype=np.bool)
        start_time = labdate.MillisecondsTimestamp()
        wall_time_start = start_time

        self.backend.InitSampleBatch(sampler, batch_size)

        # Sampling loop. Continues until all samples in the batch are done.
        while True:
          indices = self.backend.SampleNextIndices(sampler, batch_size)

          # Iterate over all samples in batch to determine whether they're
          # done.
          for i in range(batch_size):
            if done[i]:
              continue

            token = atomizer.decoder[indices[i]]
            samples_in_progress[i].append(token)
            if sampler.SampleIsComplete(samples_in_progress[i]):
              end_time = labdate.MillisecondsTimestamp()
              done[i] = 1
              sample = model_pb2.Sample(
                  text=''.join(samples_in_progress[i]),
                  sample_start_epoch_ms_utc=start_time,
                  sample_time_ms=end_time - start_time,
                  wall_time_ms=end_time - wall_time_start,
                  num_tokens=len(samples_in_progress[i]))
              sample_count += 1
              samples.append(sample)
              wall_time_start = labdate.MillisecondsTimestamp()

          # Complete the batch.
          if done.all():
            break

        # Complete sampling. Note that sample_count starts at 1.
        if sample_count > min_num_samples:
          now = labdate.MillisecondsTimestamp()
          logging.info(
              'Produced %s samples at a rate of %s ms / sample.',
              humanize.intcomma(len(samples)),
              humanize.intcomma(
                  int((now - sample_start_time) / len(samples))))
          break

    return samples

  def SamplerCache(self, sampler: samplers.Sampler) -> pathlib.Path:
    """Get the path to a sampler cache.

    Args:
      sampler: A Sampler instance.

    Returns:
      A path to a directory. Note that this directory may not exist - it is
      created only after a call to Sample().
    """
    return self.cache.path / 'samples' / sampler.hash

  def _WriteMetafile(self) -> None:
    pbutil.ToFile(self.meta, pathlib.Path(self.cache.keypath('META.pbtxt')))

  def TrainingTelemetry(self) -> typing.List[telemetry_pb2.ModelEpochTelemetry]:
    """Get the training telemetry data."""
    return telemetry.TrainingLogger(self.cache.path / 'logs').EpochTelemetry()

  def InferenceManifest(self) -> typing.List[pathlib.Path]:
    """Return the list of files which are required for model inference.

    Returns:
      A list of absolute paths.
    """
    return sorted([
                    self.cache.path / 'atomizer',
                    self.cache.path / 'META.pbtxt',
                  ] + self.backend.InferenceManifest())

  @property
  def atomizer(self) -> atomizers.AtomizerBase:
    return self.corpus.atomizer

  @property
  def training_lock(self) -> lockfile.LockFile:
    """A lockfile for exclusive training."""
    return lockfile.LockFile(self.cache.keypath('LOCK'))

  @property
  def is_trained(self) -> bool:
    return self.backend.is_trained

  def __repr__(self) -> str:
    """String representation."""
    return f'model[{self.hash}]'

  def __eq__(self, rhs) -> bool:
    if not isinstance(rhs, Model):
      return False
    return rhs.hash == self.hash

  def __ne__(self, rhs) -> bool:
    return not self.__eq__(rhs)
