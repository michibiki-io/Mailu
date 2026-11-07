"""Release selection must follow merged upstream history, not fork tag names."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "upstream_version", Path(__file__).resolve().parents[2] / "scripts/release/upstream_version.py"
)
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)


class UpstreamVersionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = Path.cwd()
        os.chdir(self.temp.name)
        self.git("init", "-q", "-b", "upstream")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("commit", "--allow-empty", "-qm", "upstream 9")
        self.nine = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/mailu-upstream/tags/2024.06.9", self.nine)
        self.git("checkout", "-qb", "fork")
        self.git("commit", "--allow-empty", "-qm", "OIDC")
        self.git("tag", "2024.06.999")  # Fork-local tags must not influence selection.
        self.git("checkout", "-q", "upstream")
        self.git("commit", "--allow-empty", "-qm", "upstream 67")
        self.latest = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/mailu-upstream/tags/2024.06.67", self.latest)
        self.git("update-ref", "refs/mailu-upstream/branch", self.latest)
        self.git("checkout", "-q", "fork")

    def tearDown(self):
        os.chdir(self.previous)
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()

    def test_does_not_claim_latest_before_merge(self):
        self.assertEqual(resolver.select_version("2024.06", ["2024.06.9", "2024.06.67"]), "2024.06.9")

    def test_merge_selects_same_upstream_version_numerically(self):
        self.git("merge", "--no-ff", "-qm", "import upstream", "upstream")
        self.assertEqual(resolver.select_version("2024.06", ["2024.06.9", "2024.06.67"]), "2024.06.67")

    def test_unpublished_tags_and_other_release_lines_are_ignored(self):
        self.git("merge", "--no-ff", "-qm", "import upstream", "upstream")
        self.assertEqual(resolver.select_version("2024.06", ["2024.06.9", "2024.06.67-rc1", "2025.01.99"]), "2024.06.9")

    def test_no_merged_published_release_fails(self):
        with self.assertRaisesRegex(RuntimeError, "merge upstream first"):
            resolver.select_version("2024.06", ["2024.06.67"])

    def test_release_on_another_branch_is_excluded(self):
        self.git("update-ref", "refs/mailu-upstream/branch", self.nine)
        self.git("merge", "--no-ff", "-qm", "import upstream", "upstream")
        self.assertEqual(resolver.select_version("2024.06", ["2024.06.9", "2024.06.67"]), "2024.06.9")

    def test_first_publication_creates_pin_and_release(self):
        self.assertEqual(resolver.publication_state("2024.06.67", [], None, "fork"), (True, True))

    def test_existing_release_preserves_fixed_image_and_tag(self):
        self.assertEqual(resolver.publication_state("2024.06.67", ["2024.06.67"], "old-fork", "new-fork"), (False, False))

    def test_imported_tag_collision_is_not_overwritten(self):
        with self.assertRaisesRegex(RuntimeError, "will not overwrite"):
            resolver.publication_state("2024.06.67", [], "upstream", "fork")

    def test_partial_release_can_resume_without_retagging_image(self):
        self.assertEqual(resolver.publication_state("2024.06.67", [], "fork", "fork"), (False, True))

    def test_dispatch_only_image_is_preserved_without_creating_a_release(self):
        self.assertEqual(resolver.publication_state(
            "2024.06.46", [], None, "new-fork", image_present=True
        ), (False, False))

    def test_image_and_matching_tag_allow_an_interrupted_release_to_resume(self):
        self.assertEqual(resolver.publication_state(
            "2024.06.67", [], "fork", "fork", image_present=True
        ), (False, True))

    @patch.object(resolver.subprocess, "run")
    def test_missing_manifest_allows_a_new_fixed_version(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stderr="ERROR: ghcr.io/fork/mailu-admin:2024.06.67: not found")
        self.assertFalse(resolver.image_exists("ghcr.io/fork/mailu-admin:2024.06.67"))

    @patch.object(resolver.subprocess, "run")
    def test_registry_access_error_does_not_allow_overwriting_an_image(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess([], 1, stderr="ERROR: unauthorized")
        with self.assertRaisesRegex(RuntimeError, "Cannot check existing image"):
            resolver.image_exists("ghcr.io/fork/mailu-admin:2024.06.46")


if __name__ == "__main__":
    unittest.main()
