"""A python wrapper around oclgrind, an OpenCL device simulator and debugger.

Oclgrind is developed by James Price <j.price@bristol.ac.uk>.
See https://github.com/jrprice/Oclgrind/wiki for the oclgrind documentation.

This file can be executed as a binary in order to invoke oclgrind. Note you must
use '--' to prevent this script from attempting to parse the args, and a second
'--' if invoked using bazel, to prevent bazel from parsing the args.

Usage:

  bazel run //gpu/oclgrind [-- -- <args>]
"""
import subprocess
import sys
import typing

from absl import app
from absl import flags

from gpu.clinfo.proto import clinfo_pb2
from labm8 import bazelutil
from labm8 import system


FLAGS = flags.FLAGS

_OCLGRIND_PKG = 'oclgrind_linux' if system.is_linux() else 'oclgrind_mac'
# The path to the oclgrind binary.
OCLGRIND_PATH = bazelutil.DataPath(f'{_OCLGRIND_PKG}/bin/oclgrind')
# The clinfo description of the local Oclgrind binary.
CLINFO_DESCRIPTION = clinfo_pb2.OpenClDevice(
    name='Emulator|Oclgrind|Oclgrind_Simulator|Oclgrind_18.3|1.2',
    platform_name='Oclgrind',
    device_name='Oclgrind Simulator',
    driver_version='Oclgrind 18.3',
    opencl_version='1.2',
    device_type='Emulator',
    platform_id=0,
    device_id=0,
)


def Exec(argv: typing.List[str],
         env: typing.Dict[str, str] = None) -> subprocess.Popen:
  """Execute a command using oclgrind.

  This creates a Popen process, executes it, and sets the stdout and stderr
  attributes to the process output.

  Args:
    argv: A list of arguments to pass to the oclgrind executable.
    env: An optional environment to use.

  Returns:
    A Popen instance, with string stdout and stderr attributes set.
  """
  cmd = [str(OCLGRIND_PATH)] + argv
  # logging.debug('$ %s', ' '.join(cmd))
  process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True,
                             env=env)
  stdout, stderr = process.communicate()
  process.stdout, process.stderr = stdout, stderr
  return process


def main(argv):
  """Main entry point."""
  proc = Exec(argv[1:])
  print(proc.stdout)
  print(proc.stderr, file=sys.stderr)
  sys.exit(proc.returncode)


if __name__ == '__main__':
  app.run(main)
