"""Build local serialized FileDescriptorSet fixtures.

Fixtures are constructed from descriptor_pb2 metadata rather than found by
source-string searches, so every map has its real nested map-entry message.
Run: python -m wire_compat.fixtures.build_fixtures [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.protobuf import descriptor_pb2

FD = descriptor_pb2.FieldDescriptorProto
MD = descriptor_pb2.DescriptorProto
SET = descriptor_pb2.FileDescriptorSet

PACKAGE = "wirecompat.demo.v1"
OLD_FILE = "library_old.proto"
NEW_FILE = "library_new.proto"
BOOK_ENTRY = ".wirecompat.demo.v1.Book.LabelsEntry"


def _field(
    name: str,
    number: int,
    label: int,
    field_type: int,
    type_name: str | None = None,
    oneof_index: int | None = None,
) -> FD:
    field = FD(name=name, number=number, label=label, type=field_type)
    if type_name is not None:
        field.type_name = type_name
    if oneof_index is not None:
        field.oneof_index = oneof_index
    return field


def _entry(
    name: str,
    key_type: int,
    value_type: int,
    value_type_name: str | None = None,
) -> MD:
    entry = MD(name=name)
    entry.options.map_entry = True
    entry.field.add(name="key", number=1, label=FD.LABEL_OPTIONAL, type=key_type)
    _field_value = entry.field.add(
        name="value", number=2, label=FD.LABEL_OPTIONAL, type=value_type
    )
    if value_type_name is not None:
        _field_value.type_name = value_type_name
    return entry


def _reserved(message: MD, start: int, end: int) -> None:
    field_range = message.reserved_range.add()
    field_range.start = start
    field_range.end = end


def _old_file() -> descriptor_pb2.FileDescriptorProto:
    file = descriptor_pb2.FileDescriptorProto(
        name=OLD_FILE, package=PACKAGE, syntax="proto3"
    )

    book = file.message_type.add(name="Book")
    book.field.add(name="id", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_INT32)
    book.field.add(
        name="title_text", number=2, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    # ISBN starts outside a oneof in the old schema.
    book.field.add(name="isbn", number=3, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING)
    book.field.add(
        name="legacy_price", number=4, label=FD.LABEL_OPTIONAL, type=FD.TYPE_INT64
    )
    book.field.add(
        name="old_tags", number=6, label=FD.LABEL_REPEATED, type=FD.TYPE_STRING
    )
    book.nested_type.add().CopyFrom(_entry("LabelsEntry", FD.TYPE_STRING, FD.TYPE_INT32))
    book.field.add(
        name="labels",
        number=7,
        label=FD.LABEL_REPEATED,
        type=FD.TYPE_MESSAGE,
        type_name=BOOK_ENTRY,
    )

    library = file.message_type.add(name="Library")
    library.field.add(
        name="name", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    library.field.add(
        name="book_ref",
        number=2,
        label=FD.LABEL_OPTIONAL,
        type=FD.TYPE_MESSAGE,
        type_name=".wirecompat.demo.v1.Book",
    )

    slots = file.message_type.add(name="Slots")
    slots.field.add(
        name="seat_count", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_INT32
    )
    slots.field.add(
        name="room_code", number=2, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )

    reservation = file.message_type.add(name="Reservation")
    reservation.field.add(
        name="confirmation", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    reservation.field.add(
        name="obsolete_note", number=3, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    reservation.field.add(
        name="internal_handle", number=4, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    review = reservation.nested_type.add(name="Review")
    review.field.add(
        name="review_text", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    review.field.add(name="stars", number=2, label=FD.LABEL_OPTIONAL, type=FD.TYPE_INT32)

    return file


def _new_file() -> descriptor_pb2.FileDescriptorProto:
    file = descriptor_pb2.FileDescriptorProto(
        name=NEW_FILE, package=PACKAGE, syntax="proto3"
    )

    book = file.message_type.add(name="Book")
    book.field.add(name="id", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_INT32)
    # Safe rename: number, wire type, cardinality, and oneof membership match.
    book.field.add(name="title", number=2, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING)
    book.oneof_decl.add(name="availability")
    # Move into oneof: same string wire type but changed oneof semantics.
    book.field.add(
        name="isbn",
        number=3,
        label=FD.LABEL_OPTIONAL,
        type=FD.TYPE_STRING,
        oneof_index=0,
    )
    _reserved(book, 4, 6)  # Deleted field 4 is covered by a reserved range.
    # Number 6 is reused: repeated string -> single string is also label flip.
    book.field.add(name="tags", number=6, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING)
    book.nested_type.add().CopyFrom(
        _entry(
            "LabelsEntry",
            FD.TYPE_STRING,
            FD.TYPE_MESSAGE,
            value_type_name=".wirecompat.demo.v1.Reservation",
        )
    )
    book.field.add(
        name="labels",
        number=7,
        label=FD.LABEL_REPEATED,
        type=FD.TYPE_MESSAGE,
        type_name=BOOK_ENTRY,
    )
    book.field.add(
        name="edition", number=8, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )

    library = file.message_type.add(name="Library")
    # Safe rename at field 1.
    library.field.add(
        name="display_name", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    library.field.add(
        name="book_ref",
        number=2,
        label=FD.LABEL_OPTIONAL,
        type=FD.TYPE_MESSAGE,
        type_name=".wirecompat.demo.v1.Book",
    )
    library.nested_type.add(name="Audit")

    slots = file.message_type.add(name="Slots")
    slots.field.add(
        name="seat_count", number=1, label=FD.LABEL_REPEATED, type=FD.TYPE_INT32
    )
    # Reused number with wire-type change: string -> int32.
    slots.field.add(
        name="room_code", number=2, label=FD.LABEL_OPTIONAL, type=FD.TYPE_INT32
    )

    reservation = file.message_type.add(name="Reservation")
    reservation.field.add(
        name="confirmation", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    # Field 3 was deleted and its number is reserved in the new descriptor.
    _reserved(reservation, 3, 4)
    # Field 4 was deleted on the old side but remains unreserved in the new set.
    review = reservation.nested_type.add(name="Review")
    review.field.add(
        name="comment", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    review.field.add(name="stars", number=2, label=FD.LABEL_OPTIONAL, type=FD.TYPE_INT32)

    return file
def build_old() -> bytes:
    file_set = SET()
    file_set.file.add().CopyFrom(_old_file())
    return file_set.SerializeToString()


def build_new() -> bytes:
    file_set = SET()
    file_set.file.add().CopyFrom(_new_file())
    return file_set.SerializeToString()


def build_missing_import() -> bytes:
    file_set = SET()
    file = file_set.file.add(name="uses_library.proto", package=PACKAGE, syntax="proto3")
    file.dependency.append("does_not_exist.proto")
    holder = file.message_type.add(name="UsesLibrary")
    holder.field.add(
        name="library",
        number=1,
        label=FD.LABEL_OPTIONAL,
        type=FD.TYPE_MESSAGE,
        type_name=".wirecompat.demo.v1.Library",
    )
    return file_set.SerializeToString()


def build_invalid_descriptor() -> bytes:
    file_set = SET()
    file = file_set.file.add(name="invalid.proto", package=PACKAGE, syntax="proto3")
    broken = file.message_type.add(name="Broken")
    broken.field.add(name="first", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_INT32)
    # Duplicate field number within one message is rejected by DescriptorPool.
    broken.field.add(
        name="second", number=1, label=FD.LABEL_OPTIONAL, type=FD.TYPE_STRING
    )
    return file_set.SerializeToString()


def write_all(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    outputs = {
        "library_old.binpb": build_old(),
        "library_new.binpb": build_new(),
        "missing_import.binpb": build_missing_import(),
        "invalid_descriptor.binpb": build_invalid_descriptor(),
    }
    paths: list[Path] = []
    for name, data in outputs.items():
        path = directory / name
        path.write_bytes(data)
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    directory = Path(argv[0]) if argv else Path(__file__).with_name("data")
    paths = write_all(directory)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
