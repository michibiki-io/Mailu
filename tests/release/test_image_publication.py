"""Check real Bake plans and the publication command without registry writes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PublicationTest(unittest.TestCase):
    def test_platforms_and_fixed_tags(self):
        with tempfile.TemporaryDirectory() as temp:
            mock = Path(temp) / "docker"
            mock.write_text('#!/usr/bin/env python3\nimport json,sys,os\nopen(os.environ["DOCKER_ARGS"],"w").write(json.dumps(sys.argv[1:]))\n')
            mock.chmod(0o755)
            image = "ghcr.io/fork/mailu-admin"
            env = dict(os.environ, PATH=temp + os.pathsep + os.environ["PATH"],
                       DESTINATION=image, SOURCE=image, VERSION="2024.06",
                       PINNED_VERSION="2024.06.67", GITHUB_RUN_ID="123", DOCKER_ARGS=temp + "/args")
            for platforms, suffixes in [
                ("linux/amd64", [""]), ("linux/arm64/v8", ["-arm"]),
                ("linux/arm/v7", ["-arm"]),
                ("linux/amd64,linux/arm64/v8,linux/arm/v7", ["", "-arm"]),
            ]:
                for pinned in ("true", "false"):
                    with self.subTest(platforms=platforms, publish_pinned=pinned):
                        subprocess.run(["bash", "scripts/release/publish-images.sh"], cwd=ROOT,
                                       env=dict(env, ARCHITECTURES=platforms, PUBLISH_PINNED=pinned), check=True)
                        args = json.loads(Path(temp, "args").read_text())
                        expected = ["buildx", "imagetools", "create", "--tag", image + ":2024.06",
                                    "--tag", image + ":latest"]
                        if pinned == "true":
                            expected += ["--tag", image + ":2024.06.67"]
                        expected += [image + ":2024.06-build-123" + suffix for suffix in suffixes]
                        self.assertEqual(args, expected)

    @unittest.skipUnless(shutil.which("docker"), "Docker Buildx is required for Bake plan validation")
    def test_bake_uses_only_oidc_images_and_matching_upstream_assets(self):
        for platforms in ["linux/amd64", "linux/arm64/v8", "linux/arm/v7",
                          "linux/amd64,linux/arm64/v8,linux/arm/v7"]:
            with self.subTest(platforms=platforms):
                env = dict(os.environ, ARCH=platforms, DOCKER_ORG="ghcr.io/fork", DOCKER_PREFIX="mailu-",
                           MAILU_VERSION="2024.06-build-123", PINNED_MAILU_VERSION="2024.06.67-build-123",
                           UPSTREAM_ADMIN_IMAGE="ghcr.io/mailu/admin:2024.06.67")
                plan = json.loads(subprocess.check_output(
                    ["docker", "buildx", "bake", "-f", "tests/build-ci.hcl", "--print"],
                    cwd=ROOT, env=env, text=True, stderr=subprocess.DEVNULL))
                self.assertEqual(plan["group"]["default"]["targets"], ["admin"])
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


if __name__ == "__main__":
    unittest.main()
