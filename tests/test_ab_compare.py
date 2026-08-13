#!/usr/bin/env python3
"""Regression tests for A/B winner logic (equal values must be tie)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ab_compare import _winner, _winner_bool  # noqa: E402


class WinnerTests(unittest.TestCase):
    def test_tie_when_equal(self):
        self.assertEqual(_winner(5, 5), "tie")
        self.assertEqual(_winner(0, 0, higher_better=False), "tie")

    def test_higher_better(self):
        self.assertEqual(_winner(3, 1), "A")
        self.assertEqual(_winner(1, 3), "B")

    def test_lower_better(self):
        self.assertEqual(_winner(1, 3, higher_better=False), "A")
        self.assertEqual(_winner(3, 1, higher_better=False), "B")

    def test_bool_tie_and_sides(self):
        self.assertEqual(_winner_bool(True, True), "tie")
        self.assertEqual(_winner_bool(False, False), "tie")
        self.assertEqual(_winner_bool(True, False), "A")
        self.assertEqual(_winner_bool(False, True), "B")


if __name__ == "__main__":
    unittest.main()
