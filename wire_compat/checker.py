"""Compare two FileDescriptorSet blobs for binary wire-read compatibility.

Alignment is by fully-qualified message name and field number.  The report is
limited to concerns of reading old serialized bytes with the new descriptor:
field number reuse, wire type changes, oneof membership changes,
repeated/singular flips, and whether removed field numbers became reserved.

It deliberately says nothing about JSON, text, source API, or business-level
compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from google.protobuf import descriptor_pb2, descriptor_pool
from google.protobuf.descriptor import FieldDescriptor


class DescriptorValidationError(Exception):
    """A FileDescriptorSet could not be loaded into a fresh DescriptorPool."""


BREAKING = "BREAKING"
CHANGE = "CHANGE"
SAFE = "SAFE"

MESSAGE_ADDED = "MESSAGE_ADDED"
MESSAGE_DELETED = "MESSAGE_DELETED"
FIELD_ADDED = "FIELD_ADDED"
FIELD_DELETED = "FIELD_DELETED"
FIELD_NUMBER_REUSED = "FIELD_NUMBER_REUSED"
WIRE_TYPE_CHANGED = "WIRE_TYPE_CHANGED"
LABEL_CHANGED = "LABEL_CHANGED"
ONEOF_CHANGED = "ONEOF_CHANGED"
MAP_SHAPE_CHANGED = "MAP_SHAPE_CHANGED"
FIELD_RENAMED = "FIELD_RENAMED"
MAP_ENTRY_WIRE_CHANGED = "MAP_ENTRY_WIRE_CHANGED"


_WIRE_TYPES = {
    FieldDescriptor.TYPE_DOUBLE: (1, "fixed64"),
    FieldDescriptor.TYPE_FLOAT: (5, "fixed32"),
    FieldDescriptor.TYPE_INT64: (0, "varint"),
    FieldDescriptor.TYPE_UINT64: (0, "varint"),
    FieldDescriptor.TYPE_INT32: (0, "varint"),
    FieldDescriptor.TYPE_FIXED64: (1, "fixed64"),
    FieldDescriptor.TYPE_FIXED32: (5, "fixed32"),
    FieldDescriptor.TYPE_BOOL: (0, "varint"),
    FieldDescriptor.TYPE_STRING: (2, "length-delimited"),
    FieldDescriptor.TYPE_GROUP: (3, "start-group"),
    FieldDescriptor.TYPE_MESSAGE: (2, "length-delimited"),
    FieldDescriptor.TYPE_BYTES: (2, "length-delimited"),
    FieldDescriptor.TYPE_UINT32: (0, "varint"),
    FieldDescriptor.TYPE_ENUM: (0, "varint"),
    FieldDescriptor.TYPE_SFIXED32: (5, "fixed32"),
    FieldDescriptor.TYPE_SFIXED64: (1, "fixed64"),
    FieldDescriptor.TYPE_SINT32: (0, "varint"),
    FieldDescriptor.TYPE_SINT64: (0, "varint"),
}


@dataclass(frozen=True)
class Event:
    """One aligned, classified difference between the two descriptor sets."""

    severity: str
    code: str
    message: str
    number: int
    old_field: Optional[str]
    new_field: Optional[str]
    reason: str
    reserved_status: Optional[str] = None

    def sort_key(self) -> Tuple[str, int, str, str]:
        return (self.message, self.number, self.code, self.old_field or "")


@dataclass(frozen=True)
class _Field:
    name: str
    number: int
    label: int
    type: int
    wire_type: int
    wire_name: str
    oneof: Optional[str]
    is_map: bool
    entry_full_name: Optional[str]
    message_type_name: Optional[str]


@dataclass(frozen=True)
class _Message:
    full_name: str
    fields: Mapping[int, _Field]
    reserved_ranges: Sequence[Tuple[int, int]]
    is_map_entry: bool


@dataclass(frozen=True)
class LoadedSet:
    files: Tuple[descriptor_pb2.FileDescriptorProto, ...]
    pool: descriptor_pool.DescriptorPool
    messages: Mapping[str, _Message]
    file_names: Tuple[str, ...]



def _topologically_sorted_files(
    files: Sequence[descriptor_pb2.FileDescriptorProto],
) -> Tuple[descriptor_pb2.FileDescriptorProto, ...]:
    by_name = {file.name: file for file in files}
    order: List[str] = []
    visited: Dict[str, int] = {}

    def visit(name: str, stack: Tuple[str, ...]) -> None:
        state = visited.get(name, 0)
        if state == 2 or name not in by_name:
            return
        if state == 1:
            cycle_start = stack.index(name)
            cycle = " -> ".join(stack[cycle_start:] + (name,))
            raise DescriptorValidationError(
                f"dependency cycle among descriptor files: {cycle}"
            )
        visited[name] = 1
        current = by_name[name]
        for dependency in current.dependency:
            visit(dependency, stack + (name,))
        visited[name] = 2
        order.append(name)

    for file in files:
        visit(file.name, ())
    return tuple(by_name[name] for name in order)


def load_descriptor_set(label: str, data: bytes) -> LoadedSet:
    """Parse bytes and validate every file in a private DescriptorPool.

    Raises DescriptorValidationError for parse failures, missing imports,
    cycles, or semantically invalid descriptors. Comparison never starts when
    either side is invalid.
    """

    file_set = descriptor_pb2.FileDescriptorSet()
    try:
        file_set.ParseFromString(data)
    except Exception as exc:
        raise DescriptorValidationError(f"{label}: cannot parse: {exc}") from exc

    if not file_set.file:
        raise DescriptorValidationError(
            f"{label}: FileDescriptorSet contains no files"
        )

    try:
        ordered = _topologically_sorted_files(file_set.file)
    except DescriptorValidationError:
        raise

    pool = descriptor_pool.DescriptorPool()
    for file in ordered:
        try:
            pool.Add(file)
        except Exception as exc:
            file_name = file.name or "<unnamed>"
            raise DescriptorValidationError(
                f"{label}: DescriptorPool rejected {file_name}: {exc}"
            ) from exc

    messages = _index_messages(label, ordered, pool)
    return LoadedSet(
        files=ordered,
        pool=pool,
        messages=messages,
        file_names=tuple(file.name for file in ordered),
    )


def _resolved_type_name(type_name: str) -> str:
    # DescriptorProto type names use a leading dot for absolute names.
    return type_name[1:] if type_name.startswith(".") else type_name


def _iter_message_protos(
    file: descriptor_pb2.FileDescriptorProto,
) -> Iterable[Tuple[str, descriptor_pb2.DescriptorProto, bool]]:
    """Yield (full name, proto, ancestor-is-map-entry) recursively."""

    def walk(
        protos: Sequence[descriptor_pb2.DescriptorProto],
        prefix: str,
        ancestor_entry: bool,
    ) -> Iterable[Tuple[str, descriptor_pb2.DescriptorProto, bool]]:
        for proto in protos:
            full_name = f"{prefix}.{proto.name}" if prefix else proto.name
            is_entry = bool(proto.options.map_entry)
            yield full_name, proto, ancestor_entry
            if not is_entry:
                yield from walk(proto.nested_type, full_name, is_entry)

    yield from walk(file.message_type, file.package, False)


def _is_synthetic_proto3_optional_oneof(
    proto: descriptor_pb2.DescriptorProto, oneof_index: int
) -> bool:
    members = [
        field
        for field in proto.field
        if field.HasField("oneof_index") and field.oneof_index == oneof_index
    ]
    return len(members) == 1 and bool(members[0].proto3_optional)


def _declared_oneof(
    proto: descriptor_pb2.DescriptorProto, field: descriptor_pb2.FieldDescriptorProto
) -> Optional[str]:
    if not field.HasField("oneof_index"):
        return None
    index = field.oneof_index
    if not 0 <= index < len(proto.oneof_decl):
        return None
    if _is_synthetic_proto3_optional_oneof(proto, index):
        return None
    return proto.oneof_decl[index].name


def _find_field_proto(
    message: descriptor_pb2.DescriptorProto, name: str
) -> Optional[descriptor_pb2.FieldDescriptorProto]:
    for field in message.field:
        if field.name == name:
            return field
    return None


def _index_messages(
    label: str,
    files: Sequence[descriptor_pb2.FileDescriptorProto],
    pool: descriptor_pool.DescriptorPool,
) -> Mapping[str, _Message]:
    messages: Dict[str, _Message] = {}
    raw_by_name: Dict[str, descriptor_pb2.DescriptorProto] = {}
    file_of: Dict[str, descriptor_pb2.FileDescriptorProto] = {}

    for file in files:
        for full_name, proto, _ancestor_entry in _iter_message_protos(file):
            raw_by_name[full_name] = proto
            file_of[full_name] = file

    for full_name, raw in raw_by_name.items():
        try:
            descriptor = pool.FindMessageTypeByName(full_name)
        except Exception as exc:
            raise DescriptorValidationError(
                f"{label}: DescriptorPool cannot resolve message {full_name}: {exc}"
            ) from exc

        file = file_of[full_name]
        fields: Dict[int, _Field] = {}
        for field in descriptor.fields:
            field_proto = _find_field_proto(raw, field.name)
            if field_proto is not None:
                oneof_name = _declared_oneof(raw, field_proto)
                declared_type_name = (
                    _resolved_type_name(field_proto.type_name)
                    if field_proto.HasField("type_name")
                    else None
                )
            else:
                oneof_name = None
                declared_type_name = (
                    field.message_type.full_name
                    if field.message_type is not None
                    else None
                )

            is_map = bool(getattr(field, "is_map", False))
            if not is_map and field.message_type is not None:
                entry_raw = raw_by_name.get(field.message_type.full_name)
                if entry_raw is not None and entry_raw.options.map_entry:
                    is_map = True
            wire_type, wire_name = _WIRE_TYPES[field.type]
            fields[field.number] = _Field(
                name=field.name,
                number=field.number,
                label=(
                    int(field_proto.label)
                    if field_proto is not None
                    else int(field.label)
                ),
                type=int(field.type),
                wire_type=wire_type,
                wire_name=wire_name,
                oneof=oneof_name,
                is_map=is_map,
                entry_full_name=field.message_type.full_name if is_map else None,
                message_type_name=declared_type_name,
            )

        ranges = tuple(
            (int(reserved.start), int(reserved.end))
            for reserved in raw.reserved_range
        )
        messages[full_name] = _Message(
            full_name=full_name,
            fields=fields,
            reserved_ranges=ranges,
            is_map_entry=bool(raw.options.map_entry),
        )

    return messages


def _is_reserved(number: int, ranges: Sequence[Tuple[int, int]]) -> bool:
    return any(start <= number < end for start, end in ranges)


def _label_text(label: int) -> str:
    if label == FieldDescriptor.LABEL_REPEATED:
        return "repeated"
    if label == FieldDescriptor.LABEL_REQUIRED:
        return "required"
    return "single"


def _field_full_name(message_name: str, field_name: Optional[str]) -> Optional[str]:
    return f"{message_name}.{field_name}" if field_name else None


def compare_sets(old: LoadedSet, new: LoadedSet) -> List[Event]:
    """Return all classified events in stable message/field/kind order."""

    events: List[Event] = []
    old_names = set(old.messages)
    new_names = set(new.messages)

    for name in sorted(old_names - new_names):
        if old.messages[name].is_map_entry:
            continue
        events.append(
            Event(
                CHANGE,
                MESSAGE_DELETED,
                name,
                -1,
                name,
                None,
                "message removed; fields referencing it must be reviewed",
            )
        )

    for name in sorted(new_names - old_names):
        if new.messages[name].is_map_entry:
            continue
        events.append(
            Event(
                CHANGE,
                MESSAGE_ADDED,
                name,
                -1,
                None,
                name,
                "message added; old serialized payloads simply omit it",
            )
        )

    for name in sorted(old_names & new_names):
        old_message = old.messages[name]
        new_message = new.messages[name]
        # Map-entry messages are inspected through their owning map field,
        # where the real key/value entry structure is visible.
        if old_message.is_map_entry or new_message.is_map_entry:
            if old_message.is_map_entry != new_message.is_map_entry:
                events.append(
                    Event(
                        BREAKING,
                        MAP_SHAPE_CHANGED,
                        name,
                        -1,
                        name if old_message.is_map_entry else None,
                        name if new_message.is_map_entry else None,
                        "map-entry status of the nested message changed",
                    )
                )
            continue
        events.extend(_compare_message(old_message, new_message, old, new))

    return sorted(events, key=Event.sort_key)


def _compare_message(
    old_message: _Message,
    new_message: _Message,
    old_set: LoadedSet,
    new_set: LoadedSet,
) -> List[Event]:
    events: List[Event] = []
    message_name = old_message.full_name
    numbers = sorted(set(old_message.fields) | set(new_message.fields))

    for number in numbers:
        old_field = old_message.fields.get(number)
        new_field = new_message.fields.get(number)

        if old_field is None:
            events.append(
                Event(
                    CHANGE,
                    FIELD_ADDED,
                    message_name,
                    number,
                    None,
                    _field_full_name(message_name, new_field.name),
                    "new field number; absent in old payloads",
                )
            )
            continue

        if new_field is None:
            reserved = _is_reserved(number, new_message.reserved_ranges)
            events.append(
                Event(
                    BREAKING if not reserved else CHANGE,
                    FIELD_DELETED,
                    message_name,
                    number,
                    _field_full_name(message_name, old_field.name),
                    None,
                    "field number removed"
                    + (
                        "; number is in a new reserved range"
                        if reserved
                        else "; number is NOT reserved and can be reused"
                    ),
                    reserved_status="reserved" if reserved else "not-reserved",
                )
            )
            continue

        events.extend(_compare_field(
            message_name, old_field, new_field, old_set, new_set
        ))

    return events


def _compare_map_entries(
    message_name: str,
    old_field: _Field,
    new_field: _Field,
    old_set: LoadedSet,
    new_set: LoadedSet,
) -> List[Event]:
    events: List[Event] = []
    old_entry = old_set.messages[old_field.entry_full_name]
    new_entry = new_set.messages[new_field.entry_full_name]
    for entry_number in (1, 2):
        old_entry_field = old_entry.fields[entry_number]
        new_entry_field = new_entry.fields[entry_number]
        if old_entry_field.wire_type == new_entry_field.wire_type:
            continue
        role = "key" if entry_number == 1 else "value"
        events.append(
            Event(
                BREAKING,
                MAP_ENTRY_WIRE_CHANGED,
                message_name,
                old_field.number,
                _field_full_name(message_name, old_field.name),
                _field_full_name(message_name, new_field.name),
                f"map {role} wire type changed from "
                f"{old_entry_field.wire_name} to {new_entry_field.wire_name} "
                f"(entry {old_field.entry_full_name} -> "
                f"{new_field.entry_full_name})",
            )
        )
    return events


def _compare_field(
    message_name: str,
    old_field: _Field,
    new_field: _Field,
    old_set: LoadedSet,
    new_set: LoadedSet,
) -> List[Event]:
    events: List[Event] = []
    old_full = _field_full_name(message_name, old_field.name)
    new_full = _field_full_name(message_name, new_field.name)

    if old_field.is_map != new_field.is_map:
        events.append(
            Event(
                BREAKING,
                MAP_SHAPE_CHANGED,
                message_name,
                old_field.number,
                old_full,
                new_full,
                "map and non-map representations were swapped",
            )
        )
        return events

    if old_field.is_map and new_field.is_map:
        entry_events = _compare_map_entries(
            message_name, old_field, new_field, old_set, new_set
        )
        if old_field.name != new_field.name:
            events.append(
                Event(
                    BREAKING if entry_events else SAFE,
                    FIELD_NUMBER_REUSED if entry_events else FIELD_RENAMED,
                    message_name,
                    old_field.number,
                    old_full,
                    new_full,
                    (
                        "map field number was reused with a changed entry "
                        "structure"
                        if entry_events
                        else "map field renamed; entry key/value wire types "
                        "are unchanged"
                    ),
                )
            )
        events.extend(entry_events)
        return events

    behavior_changed = (
        old_field.wire_type != new_field.wire_type
        or (old_field.label == FieldDescriptor.LABEL_REPEATED)
        != (new_field.label == FieldDescriptor.LABEL_REPEATED)
        or old_field.oneof != new_field.oneof
    )

    if old_field.name != new_field.name:
        if behavior_changed:
            events.append(
                Event(
                    BREAKING,
                    FIELD_NUMBER_REUSED,
                    message_name,
                    old_field.number,
                    old_full,
                    new_full,
                    "field number was reused by a field with different "
                    "binary read behavior",
                )
            )
        else:
            events.append(
                Event(
                    SAFE,
                    FIELD_RENAMED,
                    message_name,
                    old_field.number,
                    old_full,
                    new_full,
                    "field renamed; number, label, wire type and oneof "
                    "membership are unchanged",
                )
            )

    if old_field.wire_type != new_field.wire_type:
        events.append(
            Event(
                BREAKING,
                WIRE_TYPE_CHANGED,
                message_name,
                old_field.number,
                old_full,
                new_full,
                f"wire type changed from {old_field.wire_name} "
                f"to {new_field.wire_name}",
            )
        )

    old_repeated = old_field.label == FieldDescriptor.LABEL_REPEATED
    new_repeated = new_field.label == FieldDescriptor.LABEL_REPEATED
    if old_repeated != new_repeated:
        events.append(
            Event(
                BREAKING,
                LABEL_CHANGED,
                message_name,
                old_field.number,
                old_full,
                new_full,
                f"cardinality changed from {_label_text(old_field.label)} "
                f"to {_label_text(new_field.label)}; repeated and single "
                "value were swapped",
            )
        )

    if old_field.oneof != new_field.oneof:
        old_target = old_field.oneof or "<outside oneof>"
        new_target = new_field.oneof or "<outside oneof>"
        events.append(
            Event(
                BREAKING,
                ONEOF_CHANGED,
                message_name,
                old_field.number,
                old_full,
                new_full,
                f"oneof membership changed from {old_target} to {new_target}",
            )
        )

    return events


def _display(value: Optional[str]) -> str:
    return value if value is not None else "-"


def render_report(
    old: LoadedSet,
    new: LoadedSet,
    events: Sequence[Event],
    old_label: str = "old",
    new_label: str = "new",
) -> str:
    """Render deterministic plain text for console output."""

    counts = {BREAKING: 0, CHANGE: 0, SAFE: 0}
    for event in events:
        counts[event.severity] = counts.get(event.severity, 0) + 1

    lines = [
        "Protobuf FileDescriptorSet binary wire-read compatibility report",
        "Scope: protobuf binary wire reading only.",
        "This is NOT a JSON, text-format, source-API, or business compatibility report.",
        f"Validated in separate DescriptorPools: {old_label}, {new_label}",
        f"{old_label} files: " + (", ".join(sorted(old.file_names)) or "-"),
        f"{new_label} files: " + (", ".join(sorted(new.file_names)) or "-"),
        (
            "Summary: "
            f"{counts[BREAKING]} breaking, {counts[CHANGE]} add/delete/change, "
            f"{counts[SAFE]} safe"
        ),
        "",
        "Severity  Code                    Message + number",
        "--------  ----------------------  ------------------------------------",
    ]

    for event in events:
        target = event.message
        if event.number >= 0:
            target = f"{target}#{event.number}"
        lines.append(
            f"{event.severity:<8}  {event.code:<22}  {target}"
        )
        lines.append(f"             old field: {_display(event.old_field)}")
        lines.append(f"             new field: {_display(event.new_field)}")
        lines.append(f"             reason: {event.reason}")
        if event.reserved_status is not None:
            lines.append(
                f"             deleted number reserved in new: {event.reserved_status}"
            )

    if not events:
        lines.append("No aligned field or message differences were found.")

    return "\n".join(lines) + "\n"
