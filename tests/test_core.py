import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import hltv_demos as hd


class CoreTests(unittest.TestCase):
    def test_map_aliases_and_validation(self):
        self.assertEqual(hd.resolve_maps("炼狱小镇, de_mirage Inferno"), ["Inferno", "Mirage"])
        with self.assertRaises(ValueError):
            hd.resolve_maps("not-a-map")

    @patch.object(hd, "ensure_7zz", return_value="7zz")
    @patch.object(hd.subprocess, "run")
    def test_archive_listing_handles_spaces_and_rejects_traversal(self, run, _seven):
        run.return_value = Mock(returncode=0, stderr="", stdout=(
            "Path = archive.rar\nType = Rar\n\n"
            "Path = folder/team one-Inferno.dem\nSize = 42\nFolder = -\n\n"
        ))
        self.assertEqual(hd.archive_demos("archive.rar"), [{
            "member": "folder/team one-Inferno.dem", "file": "team one-Inferno.dem", "size": 42
        }])
        run.return_value.stdout = "Path = ../evil-Inferno.dem\nSize = 42\nFolder = -\n\n"
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            hd.archive_demos("archive.rar")

    def test_manifest_completion_requires_files_and_all_requested_maps(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "match-Inferno.dem").write_bytes(b"x" * 4)
            entry = {"extracted_files": {"match-Inferno.dem": 4}}
            got = hd._completed_from_manifest(entry, ["Inferno"], d)
            self.assertEqual(got[0]["note"], "manifest-skip")
            self.assertEqual(hd._completed_from_manifest(entry, ["Mirage"], d), [])
            self.assertEqual(hd._completed_from_manifest(entry, [], d), [])
            entry["archive_demos"] = ["match-Inferno.dem"]
            self.assertEqual(len(hd._completed_from_manifest(entry, [], d)), 1)

    @patch.object(hd, "archive_demos")
    def test_extract_preserves_conflicting_existing_demo(self, listing):
        listing.return_value = [{"member": "match-Inferno.dem", "file": "match-Inferno.dem", "size": 10}]
        with tempfile.TemporaryDirectory() as d:
            dest = Path(d, "match-Inferno.dem")
            dest.write_bytes(b"old")
            with self.assertRaisesRegex(RuntimeError, "conflict"):
                hd.extract("archive.rar", ["Inferno"], d)
            self.assertEqual(dest.read_bytes(), b"old")

    @patch.object(hd.cr, "get")
    def test_resume_rejects_wrong_content_range_and_keeps_part(self, get):
        response = Mock(status_code=206, headers={"content-range": "bytes 0-9/10"})
        response.iter_content.return_value = [b"6789"]
        get.return_value = response
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "a.rar")
            Path(dest + ".part").write_bytes(b"12345")
            with self.assertRaisesRegex(RuntimeError, "invalid resume"):
                hd.download("https://example.invalid/a", 10, dest)
            self.assertEqual(Path(dest + ".part").read_bytes(), b"12345")

    @patch.object(hd, "_save_manifest")
    @patch.object(hd, "_manifest", return_value={})
    @patch.object(hd, "extract", side_effect=RuntimeError("extract boom"))
    @patch.object(hd, "test_archive")
    @patch.object(hd, "archive_demos", return_value=[
        {"member": "match-Inferno.dem", "file": "match-Inferno.dem", "size": 10}
    ])
    @patch.object(hd, "resolve_demo", return_value={"r2": "u", "name": "a.rar", "size": 3})
    @patch.object(hd, "fetch_match_page", return_value=(["Inferno"], "/download/demo/7"))
    @patch.object(hd, "list_results", return_value=[{"teams": "A vs B", "score": "2-0", "path": "/m/1"}])
    @patch.object(hd, "find_event", return_value=("1", "event"))
    def test_extraction_failure_never_deletes_archive(self, *_mocks):
        with tempfile.TemporaryDirectory() as d:
            csgo = Path(d, "game", "csgo")
            csgo.mkdir(parents=True)
            downloads = Path(d, "downloads")
            downloads.mkdir()
            archive = downloads / "a.rar"
            archive.write_bytes(b"rar")
            with patch.dict(os.environ, {"HLTV_DEMOS_DL_DIR": str(downloads)}):
                result = hd._run(event="event", maps="Inferno", keep_rars=False, csgo_dir=d)
            self.assertTrue(archive.exists())
            self.assertIn("extract boom", result["errors"][0]["error"])

    @patch.object(hd, "discover_csgo", side_effect=RuntimeError("missing"))
    @patch.object(hd, "resolve_demo", return_value={"r2": "u", "name": "a.rar", "size": 5})
    @patch.object(hd, "fetch_match_page", return_value=(["Inferno"], "/download/demo/7"))
    @patch.object(hd, "list_results", return_value=[{"teams": "A vs B", "score": "2-0", "path": "/m/1"}])
    @patch.object(hd, "find_event", return_value=("1", "event"))
    def test_dry_run_does_not_require_csgo(self, *_mocks):
        result = hd._run(event="event", maps="Inferno", dry_run=True)
        self.assertEqual(result["mode"], "dry-run")
        self.assertIsNone(result["csgo_dir"])


if __name__ == "__main__":
    unittest.main()
