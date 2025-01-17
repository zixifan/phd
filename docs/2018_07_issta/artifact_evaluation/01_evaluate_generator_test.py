"""Unit tests for :01_evaluate_generator.py."""
import importlib
import sys

from absl import app

# Import the CLgen test fixtures into the global namespace. Note we can't import
# only the fixtures we need here, since we must also import any dependent
# fixtures.
from deeplearning.clgen.conftest import *
from deeplearning.deepsmith.proto import deepsmith_pb2
from deeplearning.deepsmith.proto import generator_pb2


# We must use importlib.import_module() since the package and module names start
# with digits, which is considered invalid syntax using the normal import
# keyword.
evaluate_generator = importlib.import_module(
    'docs.2018_07_issta.artifact_evaluation.01_evaluate_generator')

FLAGS = flags.FLAGS


def test_GenerateTestcases(abc_instance_config):
  """Run a tiny end-to-end test."""
  generator_config = generator_pb2.ClgenGenerator(
      instance=abc_instance_config,
      testcase_skeleton=[deepsmith_pb2.Testcase(
          toolchain='opencl',
          harness=deepsmith_pb2.Harness(
              name='cldrive',
              opts={
                'timeout_seconds': '60'
              }),
          inputs={
            'gsize': '1,1,1',
            'lsize': '1,1,1',
          }
      )]
  )
  with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d)
    evaluate_generator.GenerateTestcases(generator_config, d, 3)
    assert len(list((d / 'generated_testcases').iterdir())) >= 3
    assert len(list((d / 'generated_kernels').iterdir())) >= 3
    for f in (d / 'generated_testcases').iterdir():
      assert pbutil.ProtoIsReadable(f, deepsmith_pb2.Testcase())


def main(argv):
  """Main entry point."""
  if len(argv) > 1:
    raise app.UsageError("Unknown arguments: '{}'.".format(' '.join(argv[1:])))
  sys.exit(pytest.main([__file__, '-vv']))


if __name__ == '__main__':
  flags.FLAGS(['argv[0]', '-v=1'])
  app.run(main)
