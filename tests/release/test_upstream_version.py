"""Release selection must follow merged upstream history, not fork tag names."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

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

if __name__ == "__main__":
    unittest.main()
