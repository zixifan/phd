"""CLgen: a deep learning program generator.

The core operations of CLgen are:

  1. Preprocess and encode a corpus of handwritten example programs.
  2. Define and train a machine learning model on the corpus.
  3. Sample the trained model to generate new programs.

This program automates the execution of all three stages of the pipeline.
The pipeline can be interrupted and resumed at any time. Results are cached
across runs. Please note that many of the steps in the pipeline are extremely
compute intensive and highly parallelized. If configured with CUDA support,
any NVIDIA GPUs will be used to improve performance where possible.

Made with \033[1;31m♥\033[0;0m by Chris Cummins <chrisc.101@gmail.com>.
https://chriscummins.cc/clgen
"""
import cProfile
import contextlib
import os
import pathlib
import shutil
import sys
import traceback
import typing

from absl import app
from absl import flags
from absl import logging

from deeplearning.clgen import errors
from deeplearning.clgen import samplers
from deeplearning.clgen.models import models
from deeplearning.clgen.models import pretrained
from deeplearning.clgen.proto import clgen_pb2
from deeplearning.clgen.proto import model_pb2
from labm8 import pbutil
from labm8 import prof


FLAGS = flags.FLAGS

flags.DEFINE_string(
    'config', None,
    'Path to a clgen.Instance proto file.')
flags.DEFINE_integer(
    'min_samples', -1,
    'The minimum number of samples to make.')
flags.DEFINE_string(
    'stop_after', None,
    'Stop CLgen early. Valid options are: "corpus", or "train".')
flags.DEFINE_string(
    'print_cache_path', None,
    'Print the directory of a cache and exit. Valid options are: "corpus", '
    '"model", or "sampler".')
flags.DEFINE_bool(
    'print_preprocessed', False,
    'Print the pre-processed corpus to stdout and exit.')
flags.DEFINE_string(
    'export_model', None,
    'Path to export a trained TensorFlow model to. This exports all of the '
    'files required for sampling to specified directory. The directory can '
    'then be used as the pretrained_model field of an Instance proto config.')
flags.DEFINE_bool(
    'clgen_debug', False,
    'Enable a debugging mode of CLgen python runtime. When enabled, errors '
    'which may otherwise be caught lead to program crashes and stack traces.')
flags.DEFINE_bool(
    'clgen_profiling', False,
    'Enable CLgen self profiling. Profiling results be logged.')


class Instance(object):
  """A CLgen instance."""

  def __init__(self, config: clgen_pb2.Instance):
    """Instantiate an instance.

    Args:
      config: An Instance proto.

    Raises:
      UserError: If the instance proto contains invalid values, is missing
        a model or sampler fields.
    """
    try:
      pbutil.AssertFieldIsSet(config, 'model_specification')
      pbutil.AssertFieldIsSet(config, 'sampler')
    except pbutil.ProtoValueError as e:
      raise errors.UserError(e)

    self.working_dir = None
    if config.HasField('working_dir'):
      self.working_dir: pathlib.Path = pathlib.Path(
          os.path.expandvars(config.working_dir)).expanduser().absolute()
    # Enter a session so that the cache paths are set relative to any requested
    # working directory.
    with self.Session():
      if config.HasField('model'):
        self.model: models.Model = models.Model(config.model)
      else:
        self.model: pretrained.PreTrainedModel = pretrained.PreTrainedModel(
            pathlib.Path(config.pretrained_model))
      self.sampler: samplers.Sampler = samplers.Sampler(config.sampler)

  @contextlib.contextmanager
  def Session(self) -> 'Instance':
    """Scoped $CLGEN_CACHE value."""
    old_working_dir = os.environ.get('CLGEN_CACHE', '')
    if self.working_dir:
      os.environ['CLGEN_CACHE'] = str(self.working_dir)
    yield self
    if self.working_dir:
      os.environ['CLGEN_CACHE'] = old_working_dir

  def Train(self, *args, **kwargs) -> None:
    with self.Session():
      self.model.Train(*args, **kwargs)

  def Sample(self, *args, **kwargs) -> typing.List[model_pb2.Sample]:
    with self.Session():
      return self.model.Sample(self.sampler, *args, **kwargs)

  def ToProto(self) -> clgen_pb2.Instance:
    """Get the proto config for the instance."""
    config = clgen_pb2.Instance()
    config.working_dir = str(self.working_dir)
    config.model.CopyFrom(self.model.config)
    config.sampler.CopyFrom(self.sampler.config)
    return config

  @classmethod
  def FromFile(cls, path: pathlib.Path) -> 'Instance':
    return cls(pbutil.FromFile(path, clgen_pb2.Instance()))


def Flush():
  """Flush logging and stout/stderr outputs."""
  logging.flush()
  sys.stdout.flush()
  sys.stderr.flush()


def LogException(exception: Exception):
  """Log an error."""
  logging.error(f"""\
%s (%s)

Please report bugs at <https://github.com/ChrisCummins/phd/issues>\
""", exception, type(exception).__name__)
  sys.exit(1)


def LogExceptionWithStackTrace(exception: Exception):
  """Log an error with a stack trace."""

  # get limited stack trace
  def _msg(i, x):
    n = i + 1
    filename, lineno, fnname, _ = x
    # TODO(cec): Report filename relative to PhD root.
    loc = f'{filename}:{lineno}'
    return f'      #{n}  {loc: <18} {fnname}()'

  _, _, tb = sys.exc_info()
  NUM_ROWS = 5  # number of rows in traceback
  trace = reversed(traceback.extract_tb(tb, limit=NUM_ROWS + 1)[1:])
  message = "\n".join(_msg(*r) for r in enumerate(trace))
  logging.error("""\
%s (%s)

  stacktrace:
%s

Please report bugs at <https://github.com/ChrisCummins/phd/issues>\
""", exception, type(exception).__name__, message)
  sys.exit(1)


def RunWithErrorHandling(function_to_run: typing.Callable, *args,
                         **kwargs) -> typing.Any:
  """
  Runs the given method as the main entrypoint to a program.

  If an exception is thrown, print error message and exit. If FLAGS.debug is
  set, the exception is not caught.

  Args:
    function_to_run: The function to run.
    *args: Arguments to be passed to the function.
    **kwargs: Arguments to be passed to the function.

  Returns:
    The return value of the function when called with the given args.
  """
  if FLAGS.clgen_debug:
    # Enable verbose stack traces. See: https://pymotw.com/2/cgitb/
    import cgitb
    cgitb.enable(format='text')
    return function_to_run(*args, **kwargs)

  try:
    def RunContext():
      """Run the function with arguments."""
      return function_to_run(*args, **kwargs)

    if prof.is_enabled():
      return cProfile.runctx('RunContext()', None, locals(), sort='tottime')
    else:
      return RunContext()
  except app.UsageError as err:
    # UsageError is handled by the call to app.run(), not here.
    raise err
  except errors.UserError as err:
    logging.error("%s (%s)", err, type(err).__name__)
    sys.exit(1)
  except KeyboardInterrupt:
    Flush()
    print("\nReceived keyboard interrupt, terminating", file=sys.stderr)
    sys.exit(1)
  except errors.File404 as e:
    Flush()
    LogException(e)
    sys.exit(1)
  except Exception as e:
    Flush()
    LogExceptionWithStackTrace(e)
    sys.exit(1)


def DoFlagsAction():
  """Do the action requested by the command line flags."""
  if not FLAGS.config:
    raise app.UsageError("Missing required argument: '--config'")
  config_path = pathlib.Path(FLAGS.config)
  if not config_path.is_file():
    raise app.UsageError(f"File not found: '{config_path}'")
  config = pbutil.FromFile(config_path, clgen_pb2.Instance())
  os.environ['PWD'] = str(config_path.parent)

  if FLAGS.clgen_profiling:
    prof.enable()

  instance = Instance(config)
  with instance.Session():
    if FLAGS.print_cache_path == 'corpus':
      print(instance.model.corpus.cache.path)
      return
    elif FLAGS.print_cache_path == 'model':
      print(instance.model.cache.path)
      return
    elif FLAGS.print_cache_path == 'sampler':
      print(instance.model.SamplerCache(instance.sampler))
      return
    elif FLAGS.print_cache_path:
      raise app.UsageError(
          f"Invalid --print_cache_path argument: '{FLAGS.print_cache_path}'")

    if FLAGS.print_preprocessed:
      print(instance.model.corpus.GetTextCorpus(shuffle=False))
      return

    # The default action is to sample the model.
    if FLAGS.stop_after == 'corpus':
      instance.model.corpus.Create()
    elif FLAGS.stop_after == 'train':
      instance.model.Train()
      logging.info('Model: %s', instance.model.cache.path)
    elif FLAGS.stop_after:
      raise app.UsageError(
          f"Invalid --stop_after argument: '{FLAGS.stop_after}'")
    elif FLAGS.export_model:
      instance.model.Train()
      export_dir = pathlib.Path(FLAGS.export_model)
      for path in instance.model.InferenceManifest():
        relpath = pathlib.Path(os.path.relpath(path, instance.model.cache.path))
        (export_dir / relpath.parent).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, export_dir / relpath)
        print(export_dir / relpath)
    else:
      instance.model.Sample(instance.sampler, FLAGS.min_samples)


def main(argv):
  """Main entry point."""
  if len(argv) > 1:
    raise app.UsageError(
        "Unrecognized command line options: '{}'".format(' '.join(argv[1:])))

  RunWithErrorHandling(DoFlagsAction)


if __name__ == '__main__':
  app.run(main)
