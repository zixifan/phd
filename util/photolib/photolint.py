"""A linter for ensuring that a Photo Library is organized correctly."""
import os
import sys
import time
import typing

from absl import app
from absl import flags
from absl import logging

from util.photolib import common
from util.photolib import lightroom
from util.photolib import lintercache
from util.photolib import linters
from util.photolib import workspace


FLAGS = flags.FLAGS
flags.DEFINE_string("workspace", os.getcwd(), "Path to workspace root")
flags.DEFINE_boolean("profile", False, "Print profiling timers on completion.")


class Timers(object):
  """Profiling timers."""
  total_seconds: float = 0
  linting_seconds: float = 0
  cached_seconds: float = 0


TIMERS = Timers()


class ToplevelLinter(linters.Linter):
  """A linter for top level directories."""
  __cost__ = 1

  def __init__(self, workspace_abspath: str, toplevel_dir: str,
               dirlinters: typing.List[linters.DirLinter],
               filelinters: typing.List[linters.FileLinter]):
    super(ToplevelLinter, self).__init__()
    self.workspace = workspace_abspath
    self.toplevel_dir = toplevel_dir
    self.dirlinters = linters.GetLinters(dirlinters)
    self.filelinters = linters.GetLinters(filelinters)

    linter_names = list(
        type(lin).__name__ for lin in self.dirlinters + self.filelinters)
    logging.debug("Running //%s linters: %s",
                  self.toplevel_dir, ", ".join(linter_names))

  def _LintThisDirectory(
      self, abspath: str, relpath: str,
      dirnames: typing.List[str],
      filenames: typing.List[str]) -> typing.List[linters.Error]:
    """Run linters in this directory."""
    errors = []

    # Strip files and directories which are not to be linted.
    dirnames = [d for d in dirnames if d not in common.IGNORED_DIRS]
    filenames = [f for f in filenames if f not in common.IGNORED_FILES]

    for linter in self.dirlinters:
      errors += linter(abspath, relpath, dirnames, filenames)

    for filename in filenames:
      for linter in self.filelinters:
        errors += linter(f"{abspath}/{filename}", f"{relpath}/{filename}",
                         filename) or []

    return errors

  def __call__(self, *args, **kwargs):
    start_ = time.time()

    working_dir = os.path.join(self.workspace, self.toplevel_dir)
    for abspath, dirnames, filenames in os.walk(working_dir):
      _start = time.time()
      relpath = workspace.get_workspace_relpath(self.workspace, abspath)

      cache_entry = lintercache.GetLinterErrors(abspath, relpath)

      if cache_entry.exists:
        for error in cache_entry.errors:
          linters.ERROR_COUNTS[error.category] += 1
          if not FLAGS.counts:
            print(error, file=sys.stderr)
        sys.stderr.flush()

        if FLAGS.counts:
          linters.PrintErrorCounts()

        TIMERS.cached_seconds += time.time() - _start
      else:
        errors = self._LintThisDirectory(
            abspath, relpath, dirnames, filenames)
        lintercache.AddLinterErrors(cache_entry, errors)
        TIMERS.linting_seconds += time.time() - _start

    TIMERS.total_seconds += time.time() - start_


class WorkspaceLinter(linters.Linter):
  """The master linter for the photolib workspace."""
  __cost__ = 1

  def __init__(self, abspath: str):
    super(WorkspaceLinter, self).__init__()
    self.workspace = abspath

  def __call__(self, *args, **kwargs):
    photolib_linter = ToplevelLinter(
        self.workspace, "photos",
        linters.PhotolibDirLinter, linters.PhotolibFileLinter)
    gallery_linter = ToplevelLinter(
        self.workspace, "gallery",
        linters.GalleryDirLinter, linters.GalleryFileLinter)

    photolib_linter()
    gallery_linter()


def main(argv):  # pylint: disable=missing-docstring
  del argv
  abspath = workspace.find_workspace_rootpath(
      os.path.expanduser(FLAGS.workspace))
  if not abspath:
    print(f"Cannot find workspace in '{FLAGS.workspace}'", file=sys.stderr)
    sys.exit(1)

  lightroom.InitializeKeywordsCache(abspath)
  lintercache.InitializeErrorsCache(abspath)

  WorkspaceLinter(abspath)()

  # Print the carriage return once we've done updating the counts line.
  if FLAGS.counts and linters.ERROR_COUNTS:
    print("", file=sys.stderr)

  # Print the profiling timers once we're done.
  if FLAGS.profile:
    total_time = TIMERS.total_seconds
    linting_time = TIMERS.linting_seconds
    cached_time = TIMERS.cached_seconds
    overhead = total_time - linting_time - cached_time

    print(f'linting={linting_time:.3f}s, cached={cached_time:.3f}s, '
          f'overhead={overhead:.3f}s, total={total_time:.3f}s',
          file=sys.stderr)


if __name__ == "__main__":
  try:
    app.run(main)
  except KeyboardInterrupt:
    print("interrupt")
    sys.exit(1)
