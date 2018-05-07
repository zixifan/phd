"""Unit tests for //lib/labm8:system."""

import os
import sys

import getpass
import pytest
import socket
from absl import app

from lib.labm8 import fs
from lib.labm8 import system


def test_hostname():
  hostname = socket.gethostname()
  assert hostname == system.HOSTNAME
  assert hostname == system.HOSTNAME


def test_username():
  username = getpass.getuser()
  assert username == system.USERNAME
  assert username == system.USERNAME


def test_uid():
  uid = os.getuid()
  assert uid == system.UID
  assert uid == system.UID


def test_pid():
  pid = os.getpid()
  assert pid == system.PID
  assert pid == system.PID


# ScpError
def test_ScpError():
  err = system.ScpError("out", "err")
  assert "out" == err.out
  assert "err" == err.err
  assert "out\nerr" == err.__repr__()
  assert "out\nerr" == str(err)


# Subprocess()
def test_subprocess_stdout():
  p = system.Subprocess(["echo Hello"], shell=True)
  ret, out, err = p.run()
  assert not ret
  assert out == "Hello\n"
  assert not err


def test_subprocess_stderr():
  p = system.Subprocess(["echo Hello >&2"], shell=True)
  ret, out, err = p.run()
  assert not ret
  assert err == "Hello\n"
  assert not out


def test_subprocess_timeout():
  p = system.Subprocess(["sleep 10"], shell=True)
  with pytest.raises(system.SubprocessError):
    p.run(timeout=.1)


def test_subprocess_timeout_pass():
  p = system.Subprocess(["true"], shell=True)
  ret, out, err = p.run(timeout=.1)
  assert not ret


# run()
def test_run():
  assert system.run(["true"]) == (0, None, None)
  assert system.run(["false"]) == (1, None, None)


def test_run_timeout():
  with pytest.raises(system.SubprocessError):
    system.run(["sleep 10"], timeout=.1, shell=True)
  with pytest.raises(system.SubprocessError):
    system.run(["sleep 10"], timeout=.1, num_retries=2, shell=True)


# echo()
def test_echo():
  system.echo("foo", "/tmp/labm8.tmp")
  assert fs.read("/tmp/labm8.tmp") == ["foo"]
  system.echo("", "/tmp/labm8.tmp")
  assert fs.read("/tmp/labm8.tmp") == [""]


def test_echo_append():
  system.echo("foo", "/tmp/labm8.tmp")
  system.echo("bar", "/tmp/labm8.tmp", append=True)
  assert fs.read("/tmp/labm8.tmp") == ["foo", "bar"]


def test_echo_kwargs():
  system.echo("foo", "/tmp/labm8.tmp", end="_")
  assert fs.read("/tmp/labm8.tmp") == ["foo_"]


# sed()
def test_sed():
  system.echo("Hello, world!", "/tmp/labm8.tmp")
  system.sed("Hello", "Goodbye", "/tmp/labm8.tmp")
  assert ["Goodbye, world!"] == fs.read("/tmp/labm8.tmp")
  system.sed("o", "_", "/tmp/labm8.tmp")
  assert ["G_odbye, world!"] == fs.read("/tmp/labm8.tmp")
  system.sed("o", "_", "/tmp/labm8.tmp", "g")
  assert ["G__dbye, w_rld!"] == fs.read("/tmp/labm8.tmp")


def test_sed_fail_no_file():
  with pytest.raises(system.SubprocessError):
    system.sed("Hello", "Goodbye", "/not/a/real/file")


# which()
def test_which():
  assert "/bin/sh" == system.which("sh")
  assert not system.which("not-a-real-command")


def test_which_path():
  assert system.which("sh", path=("/usr", "/bin")) == "/bin/sh"
  assert not system.which("sh", path=("/dev",))
  assert not system.which("sh", path=("/not-a-real-path",))
  assert not system.which("not-a-real-command", path=("/bin",))


# scp()
def test_scp():
  system.echo("Hello, world!", "/tmp/labm8.tmp")
  assert ["Hello, world!"] == fs.read("/tmp/labm8.tmp")
  # Cleanup any existing file.
  fs.rm("/tmp/labm8.tmp.copy")
  assert not fs.exists("/tmp/labm8.tmp.copy")
  # Perform scp.
  system.scp("localhost", "/tmp/labm8.tmp", "/tmp/labm8.tmp.copy",
             path="lib/labm8/data/test/bin")
  assert fs.read("/tmp/labm8.tmp") == fs.read("/tmp/labm8.tmp.copy")


def test_scp_user():
  system.echo("Hello, world!", "/tmp/labm8.tmp")
  assert ["Hello, world!"] == fs.read("/tmp/labm8.tmp")
  # Cleanup any existing file.
  fs.rm("/tmp/labm8.tmp.copy")
  assert not fs.exists("/tmp/labm8.tmp.copy")
  # Perform scp.
  system.scp("localhost", "/tmp/labm8.tmp", "/tmp/labm8.tmp.copy",
             path="lib/labm8/data/test/bin", user="test")
  assert fs.read("/tmp/labm8.tmp") == fs.read("/tmp/labm8.tmp.copy")


def test_scp_bad_path():
  # Error is raised if scp binary cannot be found.
  with pytest.raises(system.CommandNotFoundError):
    system.scp("localhost", "/not/a/real/path", "/tmp/labm8.tmp.copy",
               path="not/a/real/path")


def test_scp_no_scp():
  # Error is raised if scp binary cannot be found.
  with pytest.raises(system.CommandNotFoundError):
    system.scp("localhost", "/not/a/real/path", "/tmp/labm8.tmp.copy",
               path="lib/labm8/data/test")


def test_scp_bad_src():
  # Error is raised if source file cannot be found.
  with pytest.raises(system.ScpError):
    system.scp("localhost", "/not/a/real/path", "/tmp/labm8.tmp.copy",
               path="lib/labm8/data/test/bin")


def test_scp_bad_dst():
  system.echo("Hello, world!", "/tmp/labm8.tmp")
  assert ["Hello, world!"] == fs.read("/tmp/labm8.tmp")
  # Error is raised if destination file cannot be written.
  with pytest.raises(system.ScpError):
    system.scp("localhost", "/tmp/labm8.tmp", "/not/a/valid/path",
               path="lib/labm8/data/test/bin")


def test_scp_bad_dst_permission():
  system.echo("Hello, world!", "/tmp/labm8.tmp")
  assert ["Hello, world!"] == fs.read("/tmp/labm8.tmp")
  # Error is raised if no write permission for destination.
  with pytest.raises(system.ScpError):
    system.scp("localhost", "/tmp/labm8.tmp", "/dev",
               path="lib/labm8/data/test/bin")


def test_scp_bad_host():
  # Error is raised if host cannot be found.
  with pytest.raises(system.ScpError):
    system.scp("not-a-real-host", "/not/a/real/path",
               "/tmp/labm8.tmp.copy", path="lib/labm8/data/test/bin")


def test_isprocess():
  assert system.isprocess(0)
  assert system.isprocess(os.getpid())
  MAX_PROCESSES = 4194303  # OS-dependent. This value is for Linux
  assert not system.isprocess(MAX_PROCESSES + 1)


def test_exit():
  with pytest.raises(SystemExit) as ctx:
    system.exit(0)
  assert ctx.value.code == 0
  with pytest.raises(SystemExit) as ctx:
    system.exit(1)
  assert ctx.value.code == 1


def test_is_python3():
  if sys.version_info >= (3, 0):
    assert system.is_python3()
  else:
    assert not system.is_python3()


def main(argv):  # pylint: disable=missing-docstring
  del argv
  sys.exit(pytest.main([__file__, '-v']))


if __name__ == '__main__':
  app.run(main)