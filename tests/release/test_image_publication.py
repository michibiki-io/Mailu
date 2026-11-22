"""Check real Bake plans and the publication command without registry writes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
WEB_TARGETS = (("front", "nginx", "3.22.8"), ("webmail", "webmail", "3.24.3"))


class PublicationTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("docker"), "Docker Buildx is required for Bake plan validation")
    def test_bake_builds_web_images_and_uses_matching_upstream_assets(self):
        for platforms in ["linux/amd64", "linux/arm64", "linux/arm64/v8",
                          "linux/amd64,linux/arm64/v8"]:
            with self.subTest(platforms=platforms):
                env = dict(os.environ, ARCH=platforms, DOCKER_ORG="ghcr.io/fork", DOCKER_PREFIX="mailu-",
                           MAILU_VERSION="2024.06-build-123", PINNED_MAILU_VERSION="2024.06.67-build-123",
                           UPSTREAM_ADMIN_IMAGE="ghcr.io/mailu/admin:2024.06.67")
                plan = json.loads(subprocess.check_output(
                    ["docker", "buildx", "bake", "-f", "tests/build-ci.hcl", "--print"],
                    cwd=ROOT, env=env, text=True, stderr=subprocess.DEVNULL))
                self.assertEqual(plan["group"]["default"]["targets"], ["admin", "front", "webmail"])
                for target, image, distro in WEB_TARGETS:
                    self.assertEqual(plan["target"][target]["platforms"], platforms.split(","))
                    self.assertIn(f"ghcr.io/fork/mailu-{image}:2024.06-build-123",
                                  plan["target"][target]["tags"])
                    self.assert_web_base(plan, target, distro, platforms.split(","))
                admin = plan["target"]["admin"]
                self.assertEqual(set(admin["platforms"]), set(platforms.split(",")))
                self.assertEqual(admin["contexts"], {
                    "base": "docker-image://ghcr.io/fork/mailu-base:2024.06-build-123",
                    "assets": "docker-image://ghcr.io/mailu/admin:2024.06.67",
                })
                self.assertEqual(admin["args"]["ASSETS_PATH"], "/app/mailu/static")
                self.assertEqual(set(admin["tags"]), {
                    "ghcr.io/fork/mailu-admin:2024.06.67-build-123",
                    "ghcr.io/fork/mailu-admin:2024.06-build-123",
                })

    def assert_web_base(self, plan, target, distro, platforms):
        self.assertEqual(plan["target"][target]["contexts"]["base"], f"target:{target}-base")
        base = plan["target"][f"{target}-base"]
        self.assertEqual(base["context"].rstrip("/"), "core/base")
        self.assertEqual(base["target"], "web-runtime")
        self.assertEqual(base["args"]["DISTRO"], f"ghcr.io/mailu/alpine:{distro}")
        self.assertEqual(base["platforms"], platforms)

    @unittest.skipUnless(shutil.which("docker"), "Docker Buildx is required for Bake plan validation")
    def test_local_bake_uses_web_bases_and_local_admin_assets(self):
        plan = json.loads(subprocess.check_output(
            ["docker", "buildx", "bake", "-f", "tests/build.hcl", "--print", "admin", "front", "webmail"],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL))
        for target, _, distro in WEB_TARGETS:
            self.assert_web_base(plan, target, distro, ["linux/amd64"])
        self.assertEqual(plan["target"]["admin"]["contexts"], {
            "base": "target:base", "assets": "target:assets",
        })
        self.assertNotIn("DISTRO", plan["target"]["base"]["args"])


if __name__ == "__main__":
    unittest.main()
