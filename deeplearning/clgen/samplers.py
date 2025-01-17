"""Samplers for CLgen language models.

A Sampler is an object which, when passed to a mode's Sample() method,
determines the shape of the generated samples.
"""
import typing

from absl import flags

from deeplearning.clgen import errors
from deeplearning.clgen.corpuses import atomizers
from deeplearning.clgen.proto import sampler_pb2
from labm8 import crypto
from labm8 import pbutil


FLAGS = flags.FLAGS


def AssertConfigIsValid(config: sampler_pb2.Sampler) -> sampler_pb2.Sampler:
  """Assert that a sampler configuration contains no invalid values.

  Args:
    config: A sampler configuration proto.

  Returns:
    The sampler configuration proto.

  Raises:
    UserError: If there are configuration errors.
  """
  try:
    pbutil.AssertFieldConstraint(config, 'start_text', lambda s: len(s),
                                 'Sampler.start_text must be a string')
    pbutil.AssertFieldConstraint(config, 'batch_size', lambda x: 0 < x,
                                 'Sampler.batch_size must be > 0')
    pbutil.AssertFieldConstraint(config, 'temperature_micros', lambda x: 0 < x,
                                 'Sampler.temperature_micros must be > 0')
    return config
  except pbutil.ProtoValueError as e:
    raise errors.UserError(e)


class TerminationCriterionBase(object):
  """Base class for TerminationCriterion objects.

  A TerminationCriterion is an object with a single public function
  SampleIsComplete(), which accepts as its sole argument a sample-in-progress,
  and returns whether to stop sampling.
  """

  def Specialize(self, atomizer: atomizers.AtomizerBase) -> None:
    """Specialize a termination criteria to a vocabulary.

    This enables the termination criteria to set state specialized to a specific
    encoding vocabulary. This is guaranteed to be called before
    SampleIsComplete(), and ensures that the vocabulary used for all sample
    arguments to SampleIsComplete() is from this vocabulary.

    Args:
      atomizer: An atomizer to specialize to.
    """
    pass

  def SampleIsComplete(self, sample_in_progress: typing.List[str]) -> bool:
    """Determine whether to stop sampling.

    Args:
      sample_in_progress: A sample in progress, as a sequence of decoded tokens.

    Returns:
      True if the sample is "complete", else False to continue sampling.
    """
    raise NotImplementedError('abstract class')


class MaxlenTerminationCriterion(TerminationCriterionBase):
  """A termination criterion which limits the maximum length of a sample."""

  def __init__(self, config: sampler_pb2.MaxTokenLength):
    try:
      self.max_len = pbutil.AssertFieldConstraint(
          config, 'maximum_tokens_in_sample', lambda x: x > 1,
          'MaxTokenLength.maximum_tokens_in_sample must be > 0')
    except pbutil.ProtoValueError as e:
      raise errors.UserError(e)

  def SampleIsComplete(self, sample_in_progress: typing.List[str]) -> bool:
    """Determine whether to stop sampling."""
    return len(sample_in_progress) >= self.max_len


class SymmetricalTokenDepthCriterion(TerminationCriterionBase):
  """A termination criterion which counts symmetrical token depth.

  This is a generalization of bracked (i.e. { }) depth counting for C-syntax
  programming languages. When sampling to generate a C function, the sample
  is not "started" until the first { token is reached, and it is complete once
  the final } token has been emitted to close the function. In between those
  two tokens, there may be additional { } characters which increase and decrease
  the "depth" of the scope, respectively.
  """

  def __init__(self, config: sampler_pb2.SymmetricalTokenDepth):
    try:
      self.left_token = pbutil.AssertFieldConstraint(
          config, 'depth_increase_token', lambda s: len(s) > 0,
          'SymmetricalTokenDepth.depth_increase_token must be a string')
      self.right_token = pbutil.AssertFieldConstraint(
          config, 'depth_decrease_token', lambda s: len(s) > 0,
          'SymmetricalTokenDepth.depth_decrease_token must be a string')
    except pbutil.ProtoValueError as e:
      raise errors.UserError(e)
    if self.left_token == self.right_token:
      raise errors.UserError('SymmetricalTokenDepth tokens must be different')

  def Specialize(self, atomizer: atomizers.AtomizerBase) -> None:
    """Specialize a termination criteria to a vocabulary.

    This enables the termination criteria to set state specialized to a specific
    encoding vocabulary. This is guaranteed to be called before
    SampleIsComplete(), and ensures that the vocabulary used for all sample
    arguments to SampleIsComplete() is from this vocabulary.

    Args:
      atomizer: An atomizer to specialize to.

    Raises:
      InvalidSymtokTokens: If the depth tokens can't be encoded, or they encode
        to more than one token.
    """
    try:
      l = atomizer.AtomizeString(self.left_token)
      r = atomizer.AtomizeString(self.right_token)
      if len(l) > 1 or len(r) > 1:
        raise errors.InvalidSymtokTokens(
            'Sampler symmetrical depth tokens do not encode to a single '
            'token using the corpus vocabulary')
    except errors.VocabError:
      raise errors.InvalidSymtokTokens(
          'Sampler symmetrical depth tokens cannot be encoded using the '
          'corpus vocabulary')

  def SampleIsComplete(self, sample_in_progress: typing.List[str]) -> bool:
    """Determine whether to stop sampling."""
    if not sample_in_progress:
      return False
    if not sample_in_progress[-1] == self.right_token:
      return False
    left_token_count = sample_in_progress.count(self.left_token)
    right_token_count = sample_in_progress.count(self.right_token)
    # We have descending into negative depth, so abort.
    if right_token_count and not left_token_count:
      return True
    # We haven't started balancing the tokens yet.
    if not left_token_count:
      return False
    return left_token_count - right_token_count == 0


def GetTerminationCriteria(
    config: typing.List[sampler_pb2.SampleTerminationCriterion]) \
    -> typing.List[TerminationCriterionBase]:
  """Build a list of termination criteria from config protos.

  Args:
    config: A list of SampleTerminationCriterion protos.

  Returns:
    A list of TerminationCriterion instances.

  Raises:
    UserError: In case of invalid configs.
    InternalError: If any of the termination criteria are unrecognized.
  """
  terminators = []
  for criterion in config:
    if criterion.HasField('maxlen'):
      terminators.append(MaxlenTerminationCriterion(criterion.maxlen))
    elif criterion.HasField('symtok'):
      terminators.append(SymmetricalTokenDepthCriterion(criterion.symtok))
    else:
      raise errors.InternalError('Unknown Sampler.termination_criteria')
  return terminators


class Sampler(object):
  """CLgen sampler for models.

  Please note sampler instances should be treated as immutable. Upon
  instantiation, a sampler's properties are used to determine its hash. If you
  modify a property after instantiation, the hash will be out of date, which
  can lead to bad things happening.
  """

  def __init__(self, config: sampler_pb2.Sampler):
    """Instantiate a sampler.

    Args:
      config: A Sampler message.

    Raises:
      TypeError: If the config argument is not a Sampler proto.
      UserError: If the config contains invalid values.
    """
    if not isinstance(config, sampler_pb2.Sampler):
      t = type(config).__name__
      raise TypeError(f"Config must be a Sampler proto. Received: '{t}'")
    self.config = sampler_pb2.Sampler()
    self.config.CopyFrom(AssertConfigIsValid(config))
    self.hash = self._ComputeHash(self.config)
    self.terminators = GetTerminationCriteria(self.config.termination_criteria)
    self.start_text = self.config.start_text
    self.temperature = self.config.temperature_micros / 1e6
    self.batch_size = self.config.batch_size
    # Set in Specialize().
    self.encoded_start_text = None
    self.tokenized_start_text = None

  def Specialize(self, atomizer: atomizers.AtomizerBase) -> None:
    """Specialize a sampler a vocabulary.

    This enables the sampler to set state specialized to a specific encoding
    vocabulary. This is guaranteed to be called before SampleIsComplete(), and
    ensures that the vocabulary used for all sample arguments to
    SampleIsComplete() is from this vocabulary.

    Args:
      atomizer: An atomizer to specialize to.

    Raises:
      InvalidStartText: If the start_text cannot be encoded using the
        vocabulary.
      UserError: In case the sampler cannot be specialized to this vocabulary.
    """
    try:
      self.encoded_start_text = atomizer.AtomizeString(self.start_text)
      self.tokenized_start_text = atomizer.TokenizeString(self.start_text)
    except errors.VocabError:
      raise errors.InvalidStartText(
          'Sampler start text cannot be encoded using the corpus vocabulary: '
          f"'{self.start_text}'")

    [terminator.Specialize(atomizer) for terminator in self.terminators]

  def SampleIsComplete(self, sample_in_progress: typing.List[str]) -> bool:
    """Determine whether to stop sampling.

    Args:
      sample_in_progress: A sample in progress, as a sequence of decoded tokens.

    Returns:
      True if the sample is "complete", else False to continue sampling.
    """
    return any(t.SampleIsComplete(sample_in_progress) for t in self.terminators)

  @staticmethod
  def _ComputeHash(config: sampler_pb2.Sampler) -> str:
    """Compute sampler hash.

    The hash is computed from the serialized representation of the config
    proto.
    """
    return crypto.sha1(config.SerializeToString())

  def __eq__(self, rhs) -> bool:
    if not isinstance(rhs, Sampler):
      return False
    return rhs.hash == self.hash

  def __ne__(self, rhs) -> bool:
    return not self.__eq__(rhs)
