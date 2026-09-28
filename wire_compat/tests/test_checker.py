"""Unit tests for binary wire-read compatibility checks and validation."""

from __future__ import annotations

import unittest

from wire_compat.checker import (
    BREAKING,
    CHANGE,
    FIELD_ADDED,
    FIELD_DELETED,
    FIELD_NUMBER_REUSED,
    FIELD_RENAMED,
    LABEL_CHANGED,
    MAP_ENTRY_WIRE_CHANGED,
    MAP_SHAPE_CHANGED,
    MESSAGE_ADDED,
    ONEOF_CHANGED,
    SAFE,
    WIRE_TYPE_CHANGED,
    DescriptorValidationError,
    compare_sets,
    load_descriptor_set,
    render_report,
)
from wire_compat.fixtures import build_fixtures


def _load(label, payload):
    return load_descriptor_set(label, payload)


class FixtureCompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = _load("old", build_fixtures.build_old())
        cls.new = _load("new", build_fixtures.build_new())
        cls.events = compare_sets(cls.old, cls.new)

    def _event(self, message, number, code):
        matches = [
            event
            for event in self.events
            if event.message == message
            and event.number == number
            and event.code == code
        ]
        self.assertEqual(len(matches), 1, (message, number, code, self.events))
        return matches[0]

    def test_safe_rename_is_separate_from_breaking_change(self):
        renamed = self._event(
            "wirecompat.demo.v1.Book", 2, FIELD_RENAMED
        )
        self.assertEqual(renamed.severity, SAFE)
        self.assertEqual(
            renamed.old_field, "wirecompat.demo.v1.Book.title_text"
        )
        self.assertEqual(renamed.new_field, "wirecompat.demo.v1.Book.title")

        reused = self._event("wirecompat.demo.v1.Book", 6, FIELD_NUMBER_REUSED)
        self.assertEqual(reused.severity, BREAKING)
        self.assertEqual(
            reused.old_field, "wirecompat.demo.v1.Book.old_tags"
        )
        self.assertEqual(reused.new_field, "wirecompat.demo.v1.Book.tags")

    def test_oneof_migration_reported_when_wire_type_is_unchanged(self):
        event = self._event("wirecompat.demo.v1.Book", 3, ONEOF_CHANGED)
        self.assertEqual(event.severity, BREAKING)
        self.assertIn("availability", event.reason)
        self.assertIn("outside oneof", event.reason)

    def test_deleted_field_reserved_status_is_reported(self):
        covered = self._event("wirecompat.demo.v1.Book", 4, FIELD_DELETED)
        self.assertEqual(covered.severity, CHANGE)
        self.assertEqual(covered.reserved_status, "reserved")

        exposed = self._event(
            "wirecompat.demo.v1.Reservation", 4, FIELD_DELETED
        )
        self.assertEqual(exposed.severity, BREAKING)
        self.assertEqual(exposed.reserved_status, "not-reserved")
        self.assertIn("NOT reserved", exposed.reason)

    def test_wire_type_change_reported(self):
        event = self._event(
            "wirecompat.demo.v1.Slots", 2, WIRE_TYPE_CHANGED
        )
        self.assertEqual(event.severity, BREAKING)
        self.assertIn("length-delimited", event.reason)
        self.assertIn("varint", event.reason)

    def test_repeated_single_swap_reported(self):
        event = self._event("wirecompat.demo.v1.Slots", 1, LABEL_CHANGED)
        self.assertEqual(event.severity, BREAKING)
        self.assertIn("single", event.reason)
        self.assertIn("repeated", event.reason)

    def test_nested_message_rename_is_aligned_by_full_name_and_number(self):
        event = self._event(
            "wirecompat.demo.v1.Reservation.Review", 1, FIELD_RENAMED
        )
        self.assertEqual(event.severity, SAFE)
        self.assertEqual(
            event.old_field,
            "wirecompat.demo.v1.Reservation.Review.review_text",
        )
        self.assertEqual(
            event.new_field, "wirecompat.demo.v1.Reservation.Review.comment"
        )

    def test_map_is_judged_by_entry_key_and_value_structure(self):
        event = self._event(
            "wirecompat.demo.v1.Book", 7, MAP_ENTRY_WIRE_CHANGED
        )
        self.assertEqual(event.severity, BREAKING)
        self.assertIn("map value", event.reason)
        self.assertIn("LabelsEntry", event.reason)

    def test_addition_and_deletion_are_distinct(self):
        added = self._event("wirecompat.demo.v1.Book", 8, FIELD_ADDED)
        self.assertEqual(added.severity, CHANGE)
        message_added = next(
            event
            for event in self.events
            if event.message == "wirecompat.demo.v1.Library.Audit"
            and event.code == MESSAGE_ADDED
        )
        self.assertEqual(message_added.severity, CHANGE)

    def test_report_order_is_stable(self):
        keys = [event.sort_key() for event in self.events]
        self.assertEqual(keys, sorted(keys))

    def test_report_does_not_claim_json_or_business_compatibility(self):
        text = render_report(self.old, self.new, self.events)
        self.assertIn("binary wire reading only", text)
        self.assertIn("NOT a JSON", text)
        self.assertIn("business compatibility", text)


class ValidationTest(unittest.TestCase):
    def test_missing_import_stops_before_comparison(self):
        with self.assertRaises(DescriptorValidationError) as context:
            _load("bad", build_fixtures.build_missing_import())
        self.assertIn("does_not_exist.proto", str(context.exception))

    def test_invalid_descriptor_stops_before_comparison(self):
        with self.assertRaises(DescriptorValidationError):
            _load("bad", build_fixtures.build_invalid_descriptor())

    def test_each_side_uses_separate_descriptor_pool(self):
        first = _load("first", build_fixtures.build_old())
        second = _load("second", build_fixtures.build_old())
        self.assertIsNot(first.pool, second.pool)


class SyntheticMapShapeTest(unittest.TestCase):
    def test_map_to_plain_repeated_message_is_breaking(self):
        old_payload, new_payload = _map_switch_payloads()
        events = compare_sets(_load("old", old_payload), _load("new", new_payload))
        event = next(
            event for event in events if event.code == MAP_SHAPE_CHANGED
        )
        self.assertEqual(event.severity, BREAKING)


def _map_switch_payloads():
    from google.protobuf import descriptor_pb2

    fd = descriptor_pb2.FieldDescriptorProto
    old_set = descriptor_pb2.FileDescriptorSet()
    old_file = old_set.file.add(
        name="shape_old.proto", package="shape", syntax="proto3"
    )
    message = old_file.message_type.add(name="Shape")
    entry = message.nested_type.add(name="ItemsEntry")
    entry.options.map_entry = True
    entry.field.add(name="key", number=1, label=fd.LABEL_OPTIONAL, type=fd.TYPE_STRING)
    entry.field.add(name="value", number=2, label=fd.LABEL_OPTIONAL, type=fd.TYPE_INT32)
    message.field.add(
        name="items",
        number=1,
        label=fd.LABEL_REPEATED,
        type=fd.TYPE_MESSAGE,
        type_name=".shape.Shape.ItemsEntry",
    )

    new_set = descriptor_pb2.FileDescriptorSet()
    new_file = new_set.file.add(
        name="shape_new.proto", package="shape", syntax="proto3"
    )
    new_message = new_file.message_type.add(name="Shape")
    item = new_file.message_type.add(name="Item")
    item.field.add(name="id", number=1, label=fd.LABEL_OPTIONAL, type=fd.TYPE_INT32)
    new_message.field.add(
        name="items",
        number=1,
        label=fd.LABEL_REPEATED,
        type=fd.TYPE_MESSAGE,
        type_name=".shape.Item",
    )
    return old_set.SerializeToString(), new_set.SerializeToString()


class Proto3OptionalOneofTest(unittest.TestCase):
    def test_synthetic_oneof_is_not_oneof_migration(self):
        from google.protobuf import descriptor_pb2

        fd = descriptor_pb2.FieldDescriptorProto

        def payload(file_name, optional_flag):
            file_set = descriptor_pb2.FileDescriptorSet()
            file = file_set.file.add(
                name=file_name, package="optionalshape", syntax="proto3"
            )
            message = file.message_type.add(name="Maybe")
            field = message.field.add(
                name="value",
                number=1,
                label=fd.LABEL_OPTIONAL,
                type=fd.TYPE_INT32,
            )
            if optional_flag:
                message.oneof_decl.add(name="_value")
                field.oneof_index = 0
                field.proto3_optional = True
            return file_set.SerializeToString()

        old_set = _load("old", payload("a.proto", False))
        new_set = _load("new", payload("b.proto", True))
        events = compare_sets(old_set, new_set)
        self.assertFalse(
            any(event.code == ONEOF_CHANGED for event in events), events
        )


if __name__ == "__main__":
    unittest.main()
