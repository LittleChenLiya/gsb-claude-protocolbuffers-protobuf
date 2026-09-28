"""Binary wire-read compatibility checking for FileDescriptorSet pairs.

This package compares two serialized ``FileDescriptorSet`` blobs and reports
changes that matter for *protobuf binary wire reading only*. It is not a JSON
or business/API compatibility checker.
"""

from .checker import (
    DescriptorValidationError,
    Event,
    compare_sets,
    load_descriptor_set,
    render_report,
)

__all__ = [
    "DescriptorValidationError",
    "Event",
    "compare_sets",
    "load_descriptor_set",
    "render_report",
]
