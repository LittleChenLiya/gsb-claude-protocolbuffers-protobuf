"""End-to-end CLI tests using the checked-in local descriptor fixtures."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "wire_compat" / "fixtures" / "data"


def run_cli(*arguments):
    return subprocess.run(
        [sys.executable, "-m", "wire_compat", *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class CliTest(unittest.TestCase):
    def test_valid_pair_renders_scope_limited_report(self):
        result = run_cli(str(DATA / "library_old.binpb"), str(DATA / "library_new.binpb"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("binary wire-read compatibility report", result.stdout)
        self.assertIn("NOT a JSON", result.stdout)
        self.assertIn("MAP_ENTRY_WIRE_CHANGED", result.stdout)

    def test_fail_on_breaking_returns_one(self):
        result = run_cli(
            "--fail-on-breaking",
            str(DATA / "library_old.binpb"),
            str(DATA / "library_new.binpb"),
        )
        self.assertEqual(result.returncode, 1)

    def test_missing_import_stops_comparison_with_two(self):
        result = run_cli(
            str(DATA / "missing_import.binpb"), str(DATA / "library_new.binpb")
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid", result.stderr.lower())
        self.assertEqual(result.stdout, "")

    def test_invalid_descriptor_stops_comparison_with_two(self):
        result = run_cli(
            str(DATA / "library_old.binpb"), str(DATA / "invalid_descriptor.binpb")
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("DescriptorPool rejected", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
