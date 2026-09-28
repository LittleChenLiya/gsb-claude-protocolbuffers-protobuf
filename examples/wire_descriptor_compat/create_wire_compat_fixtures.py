"""Generates binary FileDescriptorSet fixtures for wire compatibility demos."""

import os

from google.protobuf import descriptor_pb2


OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OPTIONAL = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
REPEATED = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
TYPE_BOOL = descriptor_pb2.FieldDescriptorProto.TYPE_BOOL
TYPE_INT32 = descriptor_pb2.FieldDescriptorProto.TYPE_INT32
TYPE_MESSAGE = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
TYPE_STRING = descriptor_pb2.FieldDescriptorProto.TYPE_STRING


def field(name, number, field_type, label=OPTIONAL, type_name=None,
          oneof_index=None):
  proto = descriptor_pb2.FieldDescriptorProto(
      name=name, number=number, label=label, type=field_type)
  if type_name is not None:
    proto.type_name = type_name
  if oneof_index is not None:
    proto.oneof_index = oneof_index
  return proto


def map_entry(name, key_type, value_type):
  entry = descriptor_pb2.DescriptorProto(name=name)
  entry.options.map_entry = True
  entry.field.add(name='key', number=1, label=OPTIONAL, type=key_type)
  entry.field.add(name='value', number=2, label=OPTIONAL, type=value_type)
  return entry


def message_with_map(name, map_name, value_type, entry_name=None):
  entry_name = entry_name or map_name[0].upper() + map_name[1:] + 'Entry'
  message = descriptor_pb2.DescriptorProto(name=name)
  message.nested_type.add().CopyFrom(
      map_entry(entry_name, TYPE_STRING, value_type))
  message.field.add().CopyFrom(
      field(map_name, 1, TYPE_MESSAGE, REPEATED,
            '.wirecompat.fixture.%s.%s' % (name, entry_name)))
  return message


def old_file():
  proto = descriptor_pb2.FileDescriptorProto()
  proto.name = 'wirecompat/fixture/old.proto'
  proto.package = 'wirecompat.fixture'
  proto.syntax = 'proto3'

  root = proto.message_type.add(name='Root')
  root.field.add().CopyFrom(field('old_name', 1, TYPE_INT32))
  root.field.add().CopyFrom(field('number_as_int', 2, TYPE_INT32))
  root.field.add().CopyFrom(field('choice_field', 3, TYPE_BOOL))
  root.field.add().CopyFrom(field('removed_reserved', 4, TYPE_STRING))
  root.field.add().CopyFrom(field('removed_unreserved', 5, TYPE_STRING))
  root.field.add().CopyFrom(field('tags', 6, TYPE_STRING))

  nested = root.nested_type.add(name='Nested')
  nested.field.add().CopyFrom(field('value', 1, TYPE_INT32))

  proto.message_type.add().CopyFrom(
      message_with_map('Labels', 'labels', TYPE_INT32))
  proto.message_type.add().CopyFrom(
      message_with_map('Payloads', 'payloads', TYPE_STRING))
  return proto


def new_file():
  proto = descriptor_pb2.FileDescriptorProto()
  proto.name = 'wirecompat/fixture/new.proto'
  proto.package = 'wirecompat.fixture'
  proto.syntax = 'proto3'

  root = proto.message_type.add(name='Root')
  root.oneof_decl.add(name='choice')
  root.field.add().CopyFrom(field('safe_new_name', 1, TYPE_INT32))
  root.field.add().CopyFrom(field('number_as_text', 2, TYPE_STRING))
  root.field.add().CopyFrom(field('choice_field', 3, TYPE_BOOL,
                                  oneof_index=0))
  root.reserved_range.add(start=4, end=5)
  root.field.add().CopyFrom(field('added_field', 7, TYPE_STRING))
  root.field.add().CopyFrom(field('tags', 6, TYPE_STRING, REPEATED))

  nested = root.nested_type.add(name='Nested')
  nested.field.add().CopyFrom(field('renamed_value', 1, TYPE_INT32))

  proto.message_type.add().CopyFrom(
      message_with_map('Labels', 'labels', TYPE_INT32))
  proto.message_type.add().CopyFrom(
      message_with_map('Payloads', 'payloads', TYPE_BOOL))
  return proto


def descriptor_set(file_proto):
  proto_set = descriptor_pb2.FileDescriptorSet()
  proto_set.file.add().CopyFrom(file_proto)
  return proto_set


def write_fixtures():
  fixtures = [
      ('old_fds.binpb', descriptor_set(old_file())),
      ('new_fds.binpb', descriptor_set(new_file())),
  ]
  for filename, proto_set in fixtures:
    with open(os.path.join(OUTPUT_DIR, filename), 'wb') as output:
      output.write(proto_set.SerializeToString())


if __name__ == '__main__':
  write_fixtures()
