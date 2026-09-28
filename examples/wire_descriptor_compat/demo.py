"""Runs the binary FileDescriptorSet compatibility checker on local fixtures."""

import os
import subprocess
import sys


def _source_root():
  root = os.path.abspath(os.path.dirname(__file__))
  source_checker = os.path.normpath(
      os.path.join(root, '..', '..', 'python', 'google', 'protobuf',
                   'descriptor_compat.py'))
  if os.path.exists(source_checker):
    return os.path.normpath(os.path.join(root, '..', '..'))
  workspace_dir = os.environ.get('BUILD_WORKSPACE_DIRECTORY')
  if workspace_dir:
    return workspace_dir
  return os.getcwd()


FIXTURE_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
  old_fixture = os.path.join(FIXTURE_DIR, 'old_fds.binpb')
  new_fixture = os.path.join(FIXTURE_DIR, 'new_fds.binpb')
  root = _source_root()
  checker = os.path.join(
      root, 'python', 'google', 'protobuf', 'descriptor_compat.py')
  if os.path.exists(checker):
    command = [sys.executable, checker, old_fixture, new_fixture]
    return subprocess.call(command, cwd=root)

  from google.protobuf import descriptor_compat
  return descriptor_compat.main([old_fixture, new_fixture])


if __name__ == '__main__':
  sys.exit(main())
