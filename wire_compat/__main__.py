"""Command-line entry point: python -m wire_compat OLD.pb NEW.pb."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .checker import (
    BREAKING,
    DescriptorValidationError,
    compare_sets,
    load_descriptor_set,
    render_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check two serialized FileDescriptorSet files for protobuf binary "
            "wire-read compatibility. Not a JSON or business compatibility tool."
        )
    )
    parser.add_argument("old", help="old serialized FileDescriptorSet")
    parser.add_argument("new", help="new serialized FileDescriptorSet")
    parser.add_argument(
        "--fail-on-breaking",
        action="store_true",
        help="exit 1 when binary-breaking events are present",
    )
    args = parser.parse_args(argv)

    try:
        old_data = Path(args.old).read_bytes()
        new_data = Path(args.new).read_bytes()
        old_set = load_descriptor_set("old", old_data)
        new_set = load_descriptor_set("new", new_data)
    except (OSError, DescriptorValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "comparison stopped because an input descriptor was invalid",
            file=sys.stderr,
        )
        return 2

    events = compare_sets(old_set, new_set)
    print(render_report(old_set, new_set, events, args.old, args.new), end="")
    if args.fail_on_breaking and any(event.severity == BREAKING for event in events):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
