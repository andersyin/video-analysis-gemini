#!/usr/bin/env python3
"""Path helper and placeholder-refusal tests (no ffmpeg / Gemini)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import local_paths  # noqa: E402
from cross_validate import extract_template  # noqa: E402
from vc_cross_acct import normalize_vc  # noqa: E402


class PlaceholderTests(unittest.TestCase):
    def test_detects_placeholder(self):
        self.assertTrue(local_paths.has_placeholder("{{MEDIA_DIR}}/analysis_archive"))
        self.assertTrue(local_paths.has_placeholder("/tmp/{{KB_BASE}}/x"))
        self.assertFalse(local_paths.has_placeholder("/tmp/media"))
        self.assertFalse(local_paths.has_placeholder(""))

    def test_refuse_placeholder_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            local_paths.refuse_placeholder("{{MEDIA_DIR}}", "MEDIA_DIR")
        self.assertIn("placeholder", str(ctx.exception))

    def test_refuse_placeholder_passthrough(self):
        self.assertEqual(local_paths.refuse_placeholder("/tmp/media", "MEDIA_DIR"), "/tmp/media")


class ArchiveDirTests(unittest.TestCase):
    def test_cli_value_wins(self):
        self.assertEqual(
            local_paths.resolve_archive_dir("/tmp/archive"),
            Path("/tmp/archive"),
        )

    def test_cli_placeholder_exits(self):
        with self.assertRaises(SystemExit):
            local_paths.resolve_archive_dir("{{MEDIA_DIR}}/analysis_archive")

    def test_env_media_dir(self):
        with mock.patch.dict(os.environ, {"MEDIA_DIR": "/tmp/media"}, clear=False):
            self.assertEqual(
                local_paths.resolve_archive_dir(None),
                Path("/tmp/media/analysis_archive"),
            )

    def test_missing_media_dir_exits(self):
        env = {k: v for k, v in os.environ.items() if k != "MEDIA_DIR"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                local_paths.resolve_archive_dir(None)
            self.assertIn("MEDIA_DIR", str(ctx.exception))


class LoadAnalysesTests(unittest.TestCase):
    def test_loads_analysis_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "AccountA" / "videos" / "vid01"
            dest.mkdir(parents=True)
            payload = {"cinematography": {"shot_timeline": []}}
            (dest / "analysis_2026-08-13.json").write_text(
                json.dumps(payload), encoding="utf-8")
            (root / "_process_archive").mkdir()
            rows = local_paths.load_analyses(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "AccountA")
            self.assertEqual(rows[0][1], "vid01")
            self.assertEqual(rows[0][2]["cinematography"], payload["cinematography"])

    def test_missing_archive_exits(self):
        with self.assertRaises(SystemExit):
            local_paths.load_analyses("/tmp/does-not-exist-video-analysis-gemini")


class StatusDirTests(unittest.TestCase):
    def test_tmp_when_kb_unset_or_placeholder(self):
        env = {k: v for k, v in os.environ.items() if k != "KB_BASE"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(local_paths.default_status_dir(), Path("/tmp"))
        with mock.patch.dict(os.environ, {"KB_BASE": "{{KB_BASE}}"}, clear=False):
            self.assertEqual(local_paths.default_status_dir(), Path("/tmp"))

    def test_kb_base_when_set(self):
        with mock.patch.dict(os.environ, {"KB_BASE": "/tmp/kb"}, clear=False):
            self.assertEqual(
                local_paths.default_status_dir(),
                Path("/tmp/kb") / "raw" / "系统" / "watchdog心跳",
            )


class TemplateTests(unittest.TestCase):
    def test_extract_template(self):
        self.assertEqual(
            extract_template("【1.0-2.0s】特写（SubjectA）固定切镜"),
            "特写+固定切镜",
        )

    def test_normalize_vc_strips_prefix(self):
        out = normalize_vc("【1.0-2.0s】特写（SubjectA）在沙发转圈")
        self.assertNotIn("【", out)
        self.assertNotIn("SubjectA", out)


class ImportSafetyTests(unittest.TestCase):
    def test_audit_modules_import_without_running(self):
        import cross_validate
        import vo_quality_check
        import vc_cross_acct
        self.assertTrue(callable(cross_validate.main))
        self.assertTrue(callable(vo_quality_check.main))
        self.assertTrue(callable(vc_cross_acct.main))


if __name__ == "__main__":
    unittest.main()
