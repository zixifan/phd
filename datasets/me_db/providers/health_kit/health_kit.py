"""Import data from HealthKit."""
import multiprocessing
import pathlib
import subprocess
import tempfile
import typing
import zipfile

from absl import app
from absl import flags
from absl import logging

from datasets.me_db import importers
from datasets.me_db import me_pb2
from labm8 import bazelutil
from labm8 import pbutil


FLAGS = flags.FLAGS

flags.DEFINE_string('healthkit_inbox', None, 'Inbox to process.')


def ProcessXmlFile(path: pathlib.Path) -> me_pb2.SeriesCollection:
  """Process a HealthKit XML data export.

  Args:
    path: Path of the XML file.

  Returns:
    A SeriesCollection message.

  Raises:
    FileNotFoundError: If the requested file is not found.
  """
  if not path.is_file():
    raise FileNotFoundError(str(path))
  try:
    return pbutil.RunProcessMessageInPlace(
        [str(
            bazelutil.DataPath(
                'phd/datasets/me_db/providers/health_kit/xml_export_worker'))],
        me_pb2.SeriesCollection(source=str(path)))
  except subprocess.CalledProcessError as e:
    raise importers.ImporterError('HealthKit', path, str(e)) from e


def ProcessInbox(inbox: pathlib.Path) -> me_pb2.SeriesCollection:
  """Process a directory of HealthKit data.

  Args:
    inbox: The inbox path.

  Returns:
    A SeriesCollection message.
  """
  # Do nothing is there is there's no HealthKit export.zip file.
  if not (inbox / 'health_kit' / 'export.zip').is_file():
    return me_pb2.SeriesCollection()

  logging.info('Unpacking %s', inbox / 'health_kit' / 'export.zip')
  with tempfile.TemporaryDirectory(prefix='phd_') as d:
    temp_xml = pathlib.Path(d) / 'export.xml'
    with zipfile.ZipFile(inbox / 'health_kit' / 'export.zip') as z:
      with z.open('apple_health_export/export.xml') as xml_in:
        with open(temp_xml, 'wb') as f:
          f.write(xml_in.read())

    return ProcessXmlFile(temp_xml)


def ProcessInboxToQueue(inbox: pathlib.Path, queue: multiprocessing.Queue):
  queue.put(ProcessInbox(inbox))


def main(argv: typing.List[str]):
  """Main entry point."""
  if len(argv) > 1:
    raise app.UsageError("Unknown arguments: '{}'.".format(' '.join(argv[1:])))

  print(ProcessInbox(pathlib.Path(FLAGS.healthkit_inbox)))


if __name__ == '__main__':
  app.run(main)
