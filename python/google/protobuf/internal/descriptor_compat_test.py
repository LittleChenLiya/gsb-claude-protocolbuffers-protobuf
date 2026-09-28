"""Tests for binary FileDescriptorSet wire compatibility checking."""

import io
import os
import sys
import tempfile
import unittest

from google.protobuf import descriptor_compat
from google.protobuf import descriptor_pb2


OPTIONAL = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
REPEATED = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
TYPE_BOOL = descriptor_pb2.FieldDescriptorProto.TYPE_BOOL
TYPE_INT32 = descriptor_pb2.FieldDescriptorProto.TYPE_INT32
TYPE_MESSAGE = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
TYPE_STRING = descriptor_pb2.FieldDescriptorProto.TYPE_STRING


def _field(name, number, field_type, label=OPTIONAL, type_name=None,
           oneof_index=None):
  proto = descriptor_pb2.FieldDescriptorProto(
      name=name, number=number, label=label, type=field_type)
  if type_name is not None:
    proto.type_name = type_name
  if oneof_index is not None:
    proto.oneof_index = oneof_index
  return proto


def _map_entry(full_message_name, entry_name, key_type, value_type):
  entry = descriptor_pb2.DescriptorProto(name=entry_name)
  entry.options.map_entry = True
  entry.field.add(name='key', number=1, label=OPTIONAL, type=key_type)
  entry.field.add(name='value', number=2, label=OPTIONAL, type=value_type)
  return entry


def _map_message(name, field_name, entry_name, value_type):
  message = descriptor_pb2.DescriptorProto(name=name)
  message.nested_type.add().CopyFrom(
      _map_entry('.wiretest.' + name, entry_name, TYPE_STRING, value_type))
  message.field.add().CopyFrom(
      _field(field_name, 1, TYPE_MESSAGE, REPEATED,
             '.wiretest.%s.%s' % (name, entry_name)))
  return message


def _file_set():
  proto_set = descriptor_pb2.FileDescriptorSet()
  proto = proto_set.file.add()
  proto.name = 'wiretest.proto'
  proto.package = 'wiretest'
  proto.syntax = 'proto3'
  return proto_set, proto


def _old_set():
  proto_set, proto = _file_set()
  root = proto.message_type.add(name='Root')
  root.field.add().CopyFrom(_field('old_name', 1, TYPE_INT32))
  root.field.add().CopyFrom(_field('number_as_int', 2, TYPE_INT32))
  root.field.add().CopyFrom(_field('choice_field', 3, TYPE_BOOL))
  root.field.add().CopyFrom(_field('removed_reserved', 4, TYPE_STRING))
  root.field.add().CopyFrom(_field('removed_unreserved', 5, TYPE_STRING))
  root.field.add().CopyFrom(_field('tags', 6, TYPE_STRING))
  nested = root.nested_type.add(name='Nested')
  nested.field.add().CopyFrom(_field('value', 1, TYPE_INT32))
  proto.message_type.add().CopyFrom(
      _map_message('Labels', 'labels', 'LabelsEntry', TYPE_INT32))
  proto.message_type.add().CopyFrom(
      _map_message('Payloads', 'payloads', 'OldPayloadEntry', TYPE_INT32))
  return proto_set


def _new_set():
  proto_set, proto = _file_set()
  root = proto.message_type.add(name='Root')
  root.oneof_decl.add(name='choice')
  root.field.add().CopyFrom(_field('safe_new_name', 1, TYPE_INT32))
  root.field.add().CopyFrom(_field('number_as_text', 2, TYPE_STRING))
  root.field.add().CopyFrom(
      _field('choice_field', 3, TYPE_BOOL, oneof_index=0))
  root.reserved_range.add(start=4, end=5)
  root.field.add().CopyFrom(_field('added', 7, TYPE_STRING))
  root.field.add().CopyFrom(_field('tags', 6, TYPE_STRING, REPEATED))
  nested = root.nested_type.add(name='Nested')
  nested.field.add().CopyFrom(_field('renamed_value', 1, TYPE_INT32))
  proto.message_type.add().CopyFrom(
      _map_message('Labels', 'labels', 'LabelsEntry', TYPE_INT32))
  proto.message_type.add().CopyFrom(
      _map_message('Payloads', 'payloads', 'NewPayloadEntry', TYPE_STRING))
  return proto_set


class DescriptorCompatibilityTest(unittest.TestCase):

  def assertIssue(self, issues, kind, message_name, number):
    matches = [
        issue for issue in issues
        if issue.kind == kind and issue.message_full_name == message_name and
        issue.field_number == number
    ]
    self.assertEqual(1, len(matches), [issue._asdict() for issue in issues])
    return matches[0]

  def test_compares_expected_wire_findings(self):
    issues = descriptor_compat.compare_file_descriptor_sets(
        _old_set(), _new_set())

    renamed = self.assertIssue(issues, descriptor_compat.FIELD_RENAMED,
                               'wiretest.Root', 1)
    self.assertEqual('wiretest.Root.old_name', renamed.old_field_full_name)
    self.assertEqual('wiretest.Root.safe_new_name', renamed.new_field_full_name)

    reused = self.assertIssue(issues,
                              descriptor_compat.FIELD_NUMBER_REUSED,
                              'wiretest.Root', 2)
    self.assertIn('wire type changed from 0 to 2', reused.reason)

    oneof = self.assertIssue(issues,
                             descriptor_compat.FIELD_BINARY_CHANGED,
                             'wiretest.Root', 3)
    self.assertIn('oneof membership changed from <none> to choice',
                  oneof.reason)

    self.assertIssue(issues, descriptor_compat.FIELD_DELETED_RESERVED,
                     'wiretest.Root', 4)
    self.assertIssue(issues, descriptor_compat.FIELD_DELETED,
                     'wiretest.Root', 5)
    self.assertIssue(issues, descriptor_compat.FIELD_ADDED,
                     'wiretest.Root', 7)
    self.assertIssue(issues, descriptor_compat.FIELD_BINARY_CHANGED,
                     'wiretest.Root', 6)
    self.assertNotIn('wire type changed',
                     self.assertIssue(issues,
                                      descriptor_compat.FIELD_BINARY_CHANGED,
                                      'wiretest.Root', 6).reason)
    self.assertIssue(issues, descriptor_compat.FIELD_RENAMED,
                     'wiretest.Root.Nested', 1)

    map_change = self.assertIssue(
        issues, descriptor_compat.FIELD_BINARY_CHANGED,
        'wiretest.Payloads', 1)
    self.assertIn('map entry structure changed', map_change.reason)
    self.assertIn('entry field 2 wire type changed from 0 to 2',
                  map_change.reason)
    labels_changes = [
        issue for issue in issues
        if issue.message_full_name == 'wiretest.Labels'
    ]
    self.assertEqual([], labels_changes)
    self.assertEqual(issues, sorted(issues,
                                    key=descriptor_compat._issue_sort_key))

  def test_actual_map_entry_option_controls_map_detection(self):
    old_set = _old_set()
    new_set = _new_set()
    payload_entry = new_set.file[0].message_type[2].nested_type[0]
    payload_entry.ClearField('options')

    new_model = descriptor_compat._Model(new_set)
    payload_field = new_set.file[0].message_type[2].field[0]
    self.assertFalse(descriptor_compat._is_map_field(new_model, payload_field))

  def test_repeated_entry_without_map_flag_is_not_a_wire_break(self):
    old_set = _old_set()
    new_set = _old_set()
    labels_entry = new_set.file[0].message_type[1].nested_type[0]
    labels_entry.ClearField('options')

    issues = descriptor_compat.compare_serialized_file_descriptor_sets(
        old_set.SerializeToString(), new_set.SerializeToString())
    self.assertEqual([], [
        issue for issue in issues
        if issue.message_full_name == 'wiretest.Labels'
    ])

  def test_map_entry_name_change_with_same_structure_is_safe(self):
    old_set = _old_set()
    new_set = _old_set()
    labels = new_set.file[0].message_type[1]
    labels.nested_type[0].name = 'RenamedLabelsEntry'
    labels.field[0].type_name = '.wiretest.Labels.RenamedLabelsEntry'

    issues = descriptor_compat.compare_serialized_file_descriptor_sets(
        old_set.SerializeToString(), new_set.SerializeToString())
    self.assertEqual([], [
        issue for issue in issues
        if issue.message_full_name == 'wiretest.Labels'
    ])

  def test_reserved_range_boundaries(self):
    old_set = _old_set()
    new_set = _new_set()
    root = new_set.file[0].message_type[0]
    root.ClearField('reserved_range')
    root.reserved_range.add(start=4, end=4)

    issues = descriptor_compat.compare_file_descriptor_sets(
        old_set, new_set)
    self.assertIssue(issues, descriptor_compat.FIELD_DELETED,
                     'wiretest.Root', 4)

  def test_missing_import_stops_comparison(self):
    proto_set, proto = _file_set()
    proto.dependency.append('missing.proto')
    proto.message_type.add(name='Unused')

    with self.assertRaisesRegex(
        descriptor_compat.DescriptorValidationError,
        'missing dependency'):
      descriptor_compat.parse_file_descriptor_set(proto_set.SerializeToString())

  def test_orders_embedded_files_before_descriptor_pool_validation(self):
    proto_set = descriptor_pb2.FileDescriptorSet()
    imported = proto_set.file.add()
    imported.name = 'wireimported.proto'
    imported.package = 'wiretest'
    imported.syntax = 'proto3'
    imported.message_type.add(name='Imported')

    importer = proto_set.file.add()
    importer.name = 'wireimporter.proto'
    importer.package = 'wiretest'
    importer.syntax = 'proto3'
    importer.dependency.append('wireimported.proto')
    message = importer.message_type.add(name='Importer')
    message.field.add().CopyFrom(
        _field('child', 1, TYPE_MESSAGE, type_name='.wiretest.Imported'))

    validated = descriptor_compat.parse_file_descriptor_set(
        proto_set.SerializeToString())
    self.assertEqual(['wireimported.proto', 'wireimporter.proto'],
                     [proto.name for proto in validated.file])

  def test_invalid_descriptor_stops_comparison(self):
    proto_set, proto = _file_set()
    message = proto.message_type.add(name='Invalid')
    message.field.add().CopyFrom(_field('first', 1, TYPE_INT32))
    message.field.add().CopyFrom(_field('second', 1, TYPE_INT32))

    with self.assertRaises(descriptor_compat.DescriptorValidationError):
      descriptor_compat.compare_serialized_file_descriptor_sets(
          proto_set.SerializeToString(), _new_set().SerializeToString())
    with self.assertRaises(descriptor_compat.DescriptorValidationError):
      descriptor_compat.compare_serialized_file_descriptor_sets(
          _old_set().SerializeToString(), proto_set.SerializeToString())

  def test_malformed_descriptor_set_stops_comparison(self):
    with self.assertRaises(descriptor_compat.DescriptorValidationError):
      descriptor_compat.compare_serialized_file_descriptor_sets(
          b'\xff', _new_set().SerializeToString())

  def test_report_disclaims_json_and_business_compatibility(self):
    report = descriptor_compat.format_report(
        descriptor_compat.compare_file_descriptor_sets(_old_set(),
                                                        _new_set()))
    self.assertIn('binary wire-read compatibility report', report)
    self.assertIn('not a JSON or business compatibility conclusion', report)

  def test_cli_stops_before_report_for_invalid_descriptor(self):
    # main writes a user-facing validation error to stderr.
    with tempfile.TemporaryDirectory() as temp_dir:
      invalid_path = os.path.join(temp_dir, 'invalid.binpb')
      new_path = os.path.join(temp_dir, 'new.binpb')
      with open(invalid_path, 'wb') as invalid_file:
        invalid_file.write(b'\xff')
      with open(new_path, 'wb') as new_file:
        new_file.write(_new_set().SerializeToString())
      stderr = io.StringIO()
      old_stderr = sys.stderr
      sys.stderr = stderr
      try:
        exit_code = descriptor_compat.main([invalid_path, new_path])
      finally:
        sys.stderr = old_stderr
      self.assertEqual(2, exit_code)
      self.assertIn('comparison stopped', stderr.getvalue())


if __name__ == '__main__':
  unittest.main()
