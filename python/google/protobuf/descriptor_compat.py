"""Binary wire compatibility checks for FileDescriptorSet messages.

The comparison is limited to field numbers and descriptor-visible wire
behavior. It is not a JSON, generated API, or business compatibility report.
"""

import argparse
import sys
from collections import namedtuple

from google.protobuf import descriptor_pb2
from google.protobuf import descriptor_pool


FIELD_ADDED = 'FIELD_ADDED'
FIELD_DELETED = 'FIELD_DELETED'
FIELD_DELETED_RESERVED = 'FIELD_DELETED_RESERVED'
FIELD_BINARY_CHANGED = 'FIELD_BINARY_CHANGED'
FIELD_NUMBER_REUSED = 'FIELD_NUMBER_REUSED'
FIELD_RENAMED = 'FIELD_RENAMED'
MESSAGE_ADDED = 'MESSAGE_ADDED'
MESSAGE_DELETED = 'MESSAGE_DELETED'

SEVERITY_INFO = 'INFO'
SEVERITY_WARNING = 'WARNING'
SEVERITY_ERROR = 'ERROR'

CompatibilityIssue = namedtuple('CompatibilityIssue', [
    'severity', 'kind', 'message_full_name', 'field_number',
    'old_field_full_name', 'new_field_full_name', 'reason'
])

WIRE_TYPES = {
    descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE: 1,
    descriptor_pb2.FieldDescriptorProto.TYPE_FLOAT: 5,
    descriptor_pb2.FieldDescriptorProto.TYPE_INT64: 0,
    descriptor_pb2.FieldDescriptorProto.TYPE_UINT64: 0,
    descriptor_pb2.FieldDescriptorProto.TYPE_INT32: 0,
    descriptor_pb2.FieldDescriptorProto.TYPE_FIXED64: 1,
    descriptor_pb2.FieldDescriptorProto.TYPE_FIXED32: 5,
    descriptor_pb2.FieldDescriptorProto.TYPE_BOOL: 0,
    descriptor_pb2.FieldDescriptorProto.TYPE_STRING: 2,
    descriptor_pb2.FieldDescriptorProto.TYPE_GROUP: 3,
    descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE: 2,
    descriptor_pb2.FieldDescriptorProto.TYPE_BYTES: 2,
    descriptor_pb2.FieldDescriptorProto.TYPE_UINT32: 0,
    descriptor_pb2.FieldDescriptorProto.TYPE_ENUM: 0,
    descriptor_pb2.FieldDescriptorProto.TYPE_SFIXED32: 5,
    descriptor_pb2.FieldDescriptorProto.TYPE_SFIXED64: 1,
    descriptor_pb2.FieldDescriptorProto.TYPE_SINT32: 0,
    descriptor_pb2.FieldDescriptorProto.TYPE_SINT64: 0,
}


class DescriptorValidationError(ValueError):
  """Raised when a FileDescriptorSet cannot be loaded into a pool."""


class _Model(object):

  def __init__(self, file_set):
    self.messages = {}
    self.message_order = []
    for file_proto in file_set.file:
      for message_proto in file_proto.message_type:
        self._index_message(message_proto, file_proto.package)

  def _index_message(self, message_proto, parent_full_name):
    full_name = parent_full_name + '.' + message_proto.name
    self.messages[full_name] = message_proto
    if not message_proto.options.map_entry:
      self.message_order.append(full_name)
    for nested in message_proto.nested_type:
      self._index_message(nested, full_name)


def parse_file_descriptor_set(serialized):
  file_set = descriptor_pb2.FileDescriptorSet()
  try:
    file_set.ParseFromString(serialized)
  except Exception as exc:
    raise DescriptorValidationError(
        'failed to parse FileDescriptorSet: %s' % exc) from exc
  return validate_file_descriptor_set(file_set)


def validate_file_descriptor_set(file_set):
  pool = descriptor_pool.DescriptorPool()
  files_by_name = {proto.name: proto for proto in file_set.file}
  if len(files_by_name) != len(file_set.file):
    raise DescriptorValidationError('duplicate file names in descriptor set')

  ready = set()
  visiting = set()
  ordered = []

  def visit(proto, chain):
    if proto.name in ready:
      return
    if proto.name in visiting:
      raise DescriptorValidationError(
          'cyclic file dependency: %s' % ' -> '.join(chain + [proto.name]))
    visiting.add(proto.name)
    for dependency in proto.dependency:
      if dependency in files_by_name:
        visit(files_by_name[dependency], chain + [proto.name])
      else:
        try:
          pool.FindFileByName(dependency)
        except Exception as exc:
          raise DescriptorValidationError(
              'missing dependency %r for %r: %s' %
              (dependency, proto.name, exc)) from exc
    visiting.remove(proto.name)
    ready.add(proto.name)
    ordered.append(proto)

  try:
    for proto in file_set.file:
      visit(proto, [])
    for proto in ordered:
      pool.Add(proto)
  except DescriptorValidationError:
    raise
  except Exception as exc:
    raise DescriptorValidationError(
        'DescriptorPool validation failed: %s' % exc) from exc

  try:
    validated = descriptor_pb2.FileDescriptorSet()
    for proto in ordered:
      pool.FindFileByName(proto.name).CopyToProto(validated.file.add())
    return validated
  except DescriptorValidationError:
    raise
  except Exception as exc:
    raise DescriptorValidationError(
        'DescriptorPool validation failed: %s' % exc) from exc


def compare_serialized_file_descriptor_sets(old_serialized, new_serialized):
  old_set = parse_file_descriptor_set(old_serialized)
  new_set = parse_file_descriptor_set(new_serialized)
  return compare_file_descriptor_sets(old_set, new_set)


def compare_file_descriptor_sets(old_set, new_set):
  old_model = _Model(old_set)
  new_model = _Model(new_set)
  issues = []
  all_names = sorted(set(old_model.message_order) |
                     set(new_model.message_order))
  for full_name in all_names:
    old_message = old_model.messages.get(full_name)
    new_message = new_model.messages.get(full_name)
    if old_message is None:
      issues.append(
          CompatibilityIssue(SEVERITY_INFO, MESSAGE_ADDED, full_name, None,
                              None, None, 'message added'))
    elif new_message is None:
      issues.append(
          CompatibilityIssue(SEVERITY_WARNING, MESSAGE_DELETED, full_name,
                              None, None, None, 'message deleted'))
    else:
      issues.extend(_compare_message(full_name, old_model, old_message,
                                     new_model, new_message))
  return sorted(issues, key=_issue_sort_key)


def _compare_message(full_name, old_model, old_message, new_model,
                     new_message):
  old_fields = {field.number: field for field in old_message.field}
  new_fields = {field.number: field for field in new_message.field}
  issues = []

  for number in sorted(set(old_fields) | set(new_fields)):
    old_field = old_fields.get(number)
    new_field = new_fields.get(number)
    old_full = _field_full_name(full_name, old_field)
    new_full = _field_full_name(full_name, new_field)

    if old_field is None:
      issues.append(
          CompatibilityIssue(SEVERITY_INFO, FIELD_ADDED, full_name, number,
                              None, new_full, 'field added'))
      continue
    if new_field is None:
      is_reserved = _number_is_reserved(new_message, number)
      kind = FIELD_DELETED_RESERVED if is_reserved else FIELD_DELETED
      severity = SEVERITY_INFO if is_reserved else SEVERITY_WARNING
      reason = ('field deleted and number is reserved' if is_reserved else
                'field deleted but number is not reserved')
      issues.append(
          CompatibilityIssue(severity, kind, full_name, number, old_full,
                              None, reason))
      continue

    name_changed = old_field.name != new_field.name
    reasons = []
    old_wire = _wire_type(old_field)
    new_wire = _wire_type(new_field)
    if old_wire != new_wire:
      reasons.append('wire type changed from %d to %d' %
                     (old_wire, new_wire))

    old_repeated = _is_repeated(old_field)
    new_repeated = _is_repeated(new_field)
    if old_repeated != new_repeated:
      reasons.append('cardinality changed from %s to %s' %
                     ('repeated' if old_repeated else 'single',
                      'repeated' if new_repeated else 'single'))

    old_oneof = _effective_oneof_name(old_message, old_field)
    new_oneof = _effective_oneof_name(new_message, new_field)
    if old_oneof != new_oneof:
      reasons.append('oneof membership changed from %s to %s' %
                     (_oneof_label(old_oneof), _oneof_label(new_oneof)))

    old_is_map = _is_map_field(old_model, old_field)
    new_is_map = _is_map_field(new_model, new_field)
    if old_is_map and new_is_map:
      map_reason = _compare_map_entry(old_model, old_field, new_model,
                                      new_field)
      if map_reason:
        reasons.append(map_reason)

    if reasons:
      kind = (FIELD_NUMBER_REUSED if name_changed else FIELD_BINARY_CHANGED)
      issues.append(
          CompatibilityIssue(SEVERITY_ERROR, kind, full_name, number,
                              old_full, new_full, '; '.join(reasons)))
    elif name_changed:
      issues.append(
          CompatibilityIssue(SEVERITY_INFO, FIELD_RENAMED, full_name, number,
                              old_full, new_full,
                              'field renamed without changing wire behavior'))
  return issues


def _compare_map_entry(old_model, old_field, new_model, new_field):
  old_entry = _map_entry(old_model, old_field)
  new_entry = _map_entry(new_model, new_field)
  if old_entry is None or new_entry is None:
    return ''
  old_fields = {field.number: field for field in old_entry.field}
  new_fields = {field.number: field for field in new_entry.field}
  changes = []
  for number in sorted(set(old_fields) | set(new_fields)):
    old_entry_field = old_fields.get(number)
    new_entry_field = new_fields.get(number)
    if old_entry_field is None or new_entry_field is None:
      changes.append('entry field %d added or deleted' % number)
      continue
    if _wire_type(old_entry_field) != _wire_type(new_entry_field):
      changes.append('entry field %d wire type changed from %d to %d' %
                     (number, _wire_type(old_entry_field),
                      _wire_type(new_entry_field)))
    if _is_repeated(old_entry_field) != _is_repeated(new_entry_field):
      changes.append('entry field %d cardinality changed' % number)
  if changes:
    return 'map entry structure changed: ' + ', '.join(changes)
  return ''


def _map_entry(model, field_proto):
  if not _looks_like_message_field(field_proto):
    return None
  entry = model.messages.get(_normalize_type_name(field_proto.type_name))
  if entry is not None and entry.options.map_entry:
    return entry
  return None


def _is_map_field(model, field_proto):
  return _map_entry(model, field_proto) is not None


def _looks_like_message_field(field_proto):
  return (
      field_proto.label ==
      descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED and
      field_proto.type == descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE)


def _wire_type(field_proto):
  return WIRE_TYPES.get(field_proto.type, -1)


def _is_repeated(field_proto):
  return (
      field_proto.label ==
      descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED)


def _effective_oneof_name(message_proto, field_proto):
  if not field_proto.HasField('oneof_index'):
    return None
  if field_proto.oneof_index < 0 or field_proto.oneof_index >= len(
      message_proto.oneof_decl):
    return None
  oneof = message_proto.oneof_decl[field_proto.oneof_index]
  if field_proto.proto3_optional and oneof.name == '_' + field_proto.name:
    return None
  return oneof.name


def _oneof_label(oneof_name):
  return oneof_name if oneof_name is not None else '<none>'


def _number_is_reserved(message_proto, number):
  for reserved_range in message_proto.reserved_range:
    if reserved_range.start <= number < reserved_range.end:
      return True
  return False


def _normalize_type_name(type_name):
  return type_name[1:] if type_name.startswith('.') else type_name


def _field_full_name(message_full_name, field_proto):
  if field_proto is None:
    return None
  return message_full_name + '.' + field_proto.name


def _issue_sort_key(issue):
  return (
      issue.message_full_name or '',
      issue.field_number if issue.field_number is not None else -1,
      issue.kind,
      issue.old_field_full_name or '',
      issue.new_field_full_name or '',
      issue.reason or '',
  )


def format_report(issues):
  lines = [
      'Protobuf binary wire-read compatibility report',
      ('Scope: descriptor field numbers and wire read behavior only. This is '
       'not a JSON or business compatibility conclusion.'),
  ]
  if not issues:
    lines.append('No binary wire-read compatibility findings.')
    return '\n'.join(lines)

  rows = [('SEVERITY', 'KIND', 'MESSAGE', 'FIELD', 'OLD_FIELD', 'NEW_FIELD',
           'REASON')]
  for issue in issues:
    rows.append((
        issue.severity,
        issue.kind,
        issue.message_full_name or '',
        '' if issue.field_number is None else str(issue.field_number),
        issue.old_field_full_name or '',
        issue.new_field_full_name or '',
        issue.reason or '',
    ))
  widths = [max(len(row[index]) for row in rows) for index in range(7)]
  for row_index, row in enumerate(rows):
    lines.append('  '.join(value.ljust(widths[index])
                            for index, value in enumerate(row)))
    if row_index == 0:
      lines.append('  '.join('-' * width for width in widths))
  return '\n'.join(lines)


def main(argv=None):
  parser = argparse.ArgumentParser(
      description='Compare two binary FileDescriptorSet files for wire-read '
                  'compatibility.')
  parser.add_argument('old_descriptor_set')
  parser.add_argument('new_descriptor_set')
  args = parser.parse_args(argv)
  try:
    with open(args.old_descriptor_set, 'rb') as old_file:
      old_serialized = old_file.read()
    with open(args.new_descriptor_set, 'rb') as new_file:
      new_serialized = new_file.read()
    issues = compare_serialized_file_descriptor_sets(old_serialized,
                                                      new_serialized)
  except (OSError, DescriptorValidationError) as exc:
    print('descriptor validation failed; comparison stopped: %s' % exc,
          file=sys.stderr)
    return 2
  print(format_report(issues))
  return 1 if any(issue.severity == SEVERITY_ERROR for issue in issues) else 0


if __name__ == '__main__':
  sys.exit(main())
