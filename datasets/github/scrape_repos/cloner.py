"""Clone GitHub repositories.

This looks for repo meta files and clones any which have not been cloned.
"""
import multiprocessing
import pathlib
import random
import subprocess
import threading
import typing

import humanize
import progressbar
from absl import app
from absl import flags
from absl import logging

from datasets.github.scrape_repos.proto import scrape_repos_pb2
from labm8 import fs
from labm8 import pbutil


FLAGS = flags.FLAGS

flags.DEFINE_string('clone_list', None, 'The path to a LanguageCloneList file.')
flags.DEFINE_integer('repository_clone_timeout_minutes', 30,
                     'The maximum number of minutes to attempt to clone a '
                     'repository before '
                     'quitting and moving on to the next repository.')
flags.DEFINE_integer('num_cloner_threads', 4,
                     'The number of cloner threads to spawn.')


def CloneFromMetafile(metafile: pathlib.Path) -> None:
  meta = pbutil.FromFile(metafile, scrape_repos_pb2.GitHubRepoMetadata())
  if not meta.owner and meta.name:
    logging.error('Metafile missing owner and name fields %s', metafile)
    return
  clone_dir = metafile.parent / f'{meta.owner}_{meta.name}'
  logging.debug('%s', meta)
  if (clone_dir / '.git').is_dir():
    return

  # Remove anything left over from a previous attempt.
  subprocess.check_call(['rm', '-rf', str(clone_dir)])

  cmd = ['timeout', f'{FLAGS.repository_clone_timeout_minutes}m',
         '/usr/bin/git', 'clone', meta.clone_from_url, str(clone_dir)]
  logging.debug('$ %s', ' '.join(cmd))

  # Try to checkout the repository and submodules.
  p = subprocess.Popen(cmd + ['--recursive'], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, universal_newlines=True)
  _, stderr = p.communicate()
  if p.returncode and 'submodule' in stderr:
    # Remove anything left over from a previous attempt.
    subprocess.check_call(['rm', '-rf', str(clone_dir)])
    # Try again, but this time without cloning submodules.
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True)
    _, stderr = p.communicate()

  if p.returncode:
    # Give up.
    logging.warning('\nClone failed %s:\n%s', meta.clone_from_url, stderr)
    # Remove anything left over.
    subprocess.check_call(['rm', '-rf', str(clone_dir)])


def IsRepoMetaFile(f: str):
  """Determine if a path is a GitHubRepoMetadata message."""
  return (fs.isfile(f) and pbutil.ProtoIsReadable(f,
                                                  scrape_repos_pb2.GitHubRepoMetadata()))


class AsyncWorker(threading.Thread):
  """Thread which clones github repos."""

  def __init__(self, meta_files: typing.List[pathlib.Path]):
    super(AsyncWorker, self).__init__()
    self.meta_files = meta_files
    self.max = len(meta_files)
    self.i = 0

  def run(self):
    pool = multiprocessing.Pool(FLAGS.num_cloner_threads)
    for _ in pool.imap_unordered(CloneFromMetafile, self.meta_files):
      self.i += 1


def main(argv) -> None:
  """Main entry point."""
  if len(argv) > 1:
    raise app.UsageError('Too many command-line arguments.')

  clone_list_path = pathlib.Path(FLAGS.clone_list or "")
  if not clone_list_path.is_file():
    raise app.UsageError('--clone_list is not a file.')
  clone_list = pbutil.FromFile(clone_list_path,
                               scrape_repos_pb2.LanguageCloneList())

  meta_files = []
  for language in clone_list.language:
    directory = pathlib.Path(language.destination_directory)
    if directory.is_dir():
      meta_files += [pathlib.Path(directory / f) for f in directory.iterdir() if
                     IsRepoMetaFile(f)]
  random.shuffle(meta_files)
  worker = AsyncWorker(meta_files)
  logging.info('Cloning %s repos from GitHub ...',
               humanize.intcomma(worker.max))
  bar = progressbar.ProgressBar(max_value=worker.max, redirect_stderr=True)
  worker.start()
  while worker.is_alive():
    bar.update(worker.i)
    worker.join(.5)
  bar.update(worker.i)


if __name__ == '__main__':
  app.run(main)
