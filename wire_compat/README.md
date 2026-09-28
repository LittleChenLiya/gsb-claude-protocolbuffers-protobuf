# Binary wire-read FileDescriptorSet compatibility check

`wire_compat` compares two serialized `FileDescriptorSet` blobs and reports
changes that affect reading existing **protobuf binary payloads** with the new
descriptor. Messages are aligned by fully-qualified name and fields by field
number.

This tool does **not** assess JSON, text format, generated-source API, naming
policy, semantic meaning, or business-level compatibility. A safe rename is
safe here only when the field number and binary read behavior are unchanged.

## Checks

- Reused field number where the replacement changes binary read behavior.
- Field wire-type changes (varint, fixed32, fixed64, length-delimited, group).
- Movement into or out of a real `oneof`; proto3-optional synthetic oneofs are
  not treated as wire-breaking oneof movement.
- `repeated` and single-value cardinalities being swapped.
- Deleted and added fields/messages as distinct changes.
- Whether every deleted field number is covered by a `reserved_range` in the
  new message.
- Map fields through their real nested map-entry messages: entry field `1` is
  the key and field `2` is the value. Maps are not detected with source-string
  searches.
- Stable ordering by full message name, field number, event code, and old name.

Every event includes the old and new full field names when available.

The current comparison is intentionally limited to message fields and their
nested map-entry messages. It does not report enum value number changes,
service/method changes, or top-level extension declarations; those are separate
compatibility questions.

## Input validation

Each side is parsed independently and every file is added to a fresh
`DescriptorPool` in dependency order. Missing imports, dependency cycles,
duplicate field numbers, unresolved types, and other descriptor-pool failures
make the input invalid. The CLI then stops before comparing, prints the
validation error to stderr, and exits with status `2`; no comparison report is
produced.

## Local fixtures

The checked-in binary fixtures are generated from `descriptor_pb2`, so they do
not require `protoc` and do not add or modify any `.proto` file:

- `wire_compat/fixtures/data/library_old.binpb`
- `wire_compat/fixtures/data/library_new.binpb`
- `wire_compat/fixtures/data/missing_import.binpb`
- `wire_compat/fixtures/data/invalid_descriptor.binpb`

The old/new library pair intentionally contains:

- Safe renames: `Book.title_text` -> `Book.title`,
  `Library.name` -> `Library.display_name`, and nested
  `Reservation.Review.review_text` -> `comment`.
- Oneof migration: `Book.isbn` moves from outside a oneof into `availability`.
- Reuse plus behavior change: `Book.old_tags` (repeated string) ->
  `Book.tags` (single string).
- Wire-type change: `Slots.room_code` changes string (length-delimited) to
  int32 (varint).
- Repeated/single swap: `Slots.seat_count`.
- Map entry change: `Book.LabelsEntry.value` changes int32 (varint) to message
  `Reservation` (length-delimited).
- Reserved deletion: `Book.legacy_price` and `Reservation.obsolete_note` are
  deleted and covered by new reserved ranges.
- Unreserved deletion: `Reservation.internal_handle` is deleted without a
  matching new reserved range.
- Nested message addition: `Library.Audit`; field addition: `Book.edition`.

Regenerate deterministically with:

```powershell
python -m wire_compat.fixtures.build_fixtures
```

## Demo

Run from the repository root:

```powershell
python -m wire_compat `
  wire_compat/fixtures/data/library_old.binpb `
  wire_compat/fixtures/data/library_new.binpb
```

Use `--fail-on-breaking` for automation; it exits `1` when a BREAKING event is
present after both inputs have validated successfully.

Invalid input examples stop rather than producing a partial report:

```powershell
python -m wire_compat `
  wire_compat/fixtures/data/missing_import.binpb `
  wire_compat/fixtures/data/library_new.binpb

python -m wire_compat `
  wire_compat/fixtures/data/library_old.binpb `
  wire_compat/fixtures/data/invalid_descriptor.binpb
```

## Tests

```powershell
python -m unittest discover -s wire_compat/tests -v
```

The unit tests cover safe rename versus reuse, wire-type and cardinality
changes, oneof migration, nested messages, map-entry structure, reserved
ranges, additions/deletions, stable ordering, missing imports, invalid
descriptors, and CLI stop/exit behavior.

## Runtime

Only Python and the protobuf Python runtime are required (`descriptor_pb2` and
`DescriptorPool`). The implementation uses local native Python only; no Docker,
devcontainer, or Testcontainers workflow is needed.
