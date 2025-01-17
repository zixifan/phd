"""Import files into a ContentFiles database."""
import hashlib
import multiprocessing
import os
import pathlib
import random
import subprocess
import typing

import humanize
import progressbar
from absl import app
from absl import flags
from absl import logging
from sqlalchemy import orm

from datasets.github.scrape_repos import contentfiles
from datasets.github.scrape_repos.preprocessors import preprocessors
from datasets.github.scrape_repos.preprocessors import public
from datasets.github.scrape_repos.proto import scrape_repos_pb2
from labm8 import pbutil


FLAGS = flags.FLAGS
flags.DEFINE_integer('processes', os.cpu_count(),
                     'The number of simultaneous processes.')

flags.DEFINE_string('clone_list', None, 'The path to a LanguageCloneList file.')


def ShouldImportRepo(session: orm.session.Session,
                     metafile: pathlib.Path) -> bool:
  """Determine if the repository described by a metafile should be imported.

  A repository should be imported iff:
    * The metafile is a valid GitHubRepoMetadata proto.
    * The clone directory specified in the metafile appears to be a github repo.
    * The repo does not exist in the contentfiles database.
  """
  if not (metafile.is_file() and pbutil.ProtoIsReadable(
      metafile, scrape_repos_pb2.GitHubRepoMetadata())):
    return False
  meta = pbutil.FromFile(metafile, scrape_repos_pb2.GitHubRepoMetadata())
  clone_dir = metafile.parent / f'{meta.owner}_{meta.name}'
  if not (clone_dir / '.git').is_dir():
    return False
  return not contentfiles.GitHubRepository.IsInDatabase(session, meta)


def ImportWorker(
    job: scrape_repos_pb2.ImportWorker
) -> typing.List[contentfiles.ContentFile]:
  """Import a content file."""
  relpath = job.abspath[len(str(job.clone_dir)) + 1:]
  outputs: typing.List[contentfiles.ContentFile] = []
  try:
    texts = preprocessors.Preprocess(pathlib.Path(job.clone_dir), relpath,
                                     job.all_files_relpaths, job.preprocessors)
    for i, text in enumerate(texts):
      sha256 = hashlib.sha256(text.encode('utf-8'))
      outputs.append(contentfiles.ContentFile(
          clone_from_url=job.clone_from_url,
          relpath=relpath, artifact_index=i,
          sha256=sha256.digest(), charcount=len(text),
          linecount=len(text.split('\n')), text=text))
  except UnicodeDecodeError:
    logging.warning('Failed to decode %s', relpath)
  return outputs


def ImportRepo(session: orm.session.Session,
               language: scrape_repos_pb2.LanguageToClone,
               metafile: pathlib.Path,
               pool: multiprocessing.Pool) -> None:
  """Import contentfiles from repository.

  Args:
    session: A database session to import to.
    language: The language specification for the repo.
    metafile: The repo metafile.
    pool: A multiprocessing pool.
  """
  meta = pbutil.FromFile(metafile, scrape_repos_pb2.GitHubRepoMetadata())
  clone_dir = metafile.parent / f'{meta.owner}_{meta.name}'
  repo = contentfiles.GitHubRepository.GetOrAdd(session, meta)
  repo.language = language.language

  for importer in language.importer:
    if not importer.source_code_pattern:
      logging.error('No source_code_pattern specified! Stopping now.')
      return

    pat = importer.source_code_pattern
    pat = f'{clone_dir}/{pat[1:]}' if pat[0] == '^' else f'{clone_dir}/{pat}'
    cmd = ['find', str(clone_dir), '-type', 'f', '-regex', pat, '-not',
           '-path', '*/.git/*']
    logging.debug('$ %s', ' '.join(cmd))
    paths = subprocess.check_output(
        cmd, universal_newlines=True).rstrip().split('\n')
    if len(paths) == 1 and not paths[0]:
      logging.debug('No files to import from %s', clone_dir)
      return
    logging.info("Importing %s '%s' files from %s ...",
                 humanize.intcomma(len(paths)),
                 importer.source_code_pattern, clone_dir)
    all_files_relpaths = public.GetAllFilesRelativePaths(clone_dir)
    jobs = [
      scrape_repos_pb2.ImportWorker(
          clone_from_url=meta.clone_from_url,
          clone_dir=str(clone_dir),
          abspath=p,
          all_files_relpaths=all_files_relpaths,
          preprocessors=importer.preprocessor,
      ) for p in paths
    ]
    bar = progressbar.ProgressBar(max_value=len(jobs))
    for outputs in bar(pool.imap_unordered(ImportWorker, jobs)):
      for output in outputs:
        session.add(output)


def ImportFromLanguage(db: contentfiles.ContentFiles,
                       language: scrape_repos_pb2.LanguageToClone,
                       pool: multiprocessing.Pool) -> None:
  """Import contentfiles from a language specification.

  Args:
    db: The database to import to.
    language: The language to import.
    pool: A multiprocessing pool.

  Raises:
    ValueError: If importer field not set.
  """
  if not language.importer:
    raise ValueError('LanguageToClone.importer field not set')

  with db.Session() as session:
    repos_to_import = [pathlib.Path(language.destination_directory / f) for f in
                       pathlib.Path(language.destination_directory).iterdir() if
                       ShouldImportRepo(session, pathlib.Path(
                           language.destination_directory / f))]
  random.shuffle(repos_to_import)
  logging.info('Importing %s %s repos ...',
               humanize.intcomma(len(repos_to_import)),
               language.language.capitalize())
  for metafile in repos_to_import:
    with db.Session(commit=True) as session:
      ImportRepo(session, language, metafile, pool)


def main(argv):
  """Main entry point."""
  if len(argv) > 1:
    raise app.UsageError("Unknown arguments '{}'".format(', '.join(argv[1:])))

  clone_list_path = pathlib.Path(FLAGS.clone_list or "")
  if not clone_list_path.is_file():
    raise app.UsageError('--clone_list is not a file.')
  clone_list = pbutil.FromFile(clone_list_path,
                               scrape_repos_pb2.LanguageCloneList())

  # Error early if the config contains invalid preprocessors.
  for language in clone_list.language:
    for importer in language.importer:
      [preprocessors.GetPreprocessorFunction(p) for p in importer.preprocessor]

  pool = multiprocessing.Pool(FLAGS.processes)
  for language in clone_list.language:
    d = pathlib.Path(language.destination_directory)
    d = d.parent / (str(d.name) + '.db')
    db = contentfiles.ContentFiles(f'sqlite:///{d}')
    if pathlib.Path(language.destination_directory).is_dir():
      ImportFromLanguage(db, language, pool)


if __name__ == '__main__':
  app.run(main)
