#!/usr/bin/env python3
"""Resolve the newest published upstream release actually included in this fork."""
import argparse
import os
import re
import subprocess
from pathlib import Path


NAMESPACE = "refs/mailu-upstream"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def releases(repository):
    # --paginate handles releases that are older than the first API page.
    return run(
        "gh", "api", "--paginate", f"repos/{repository}/releases?per_page=100",
        "--jq", ".[] | select(.draft == false and .prerelease == false) | .tag_name",
    ).splitlines()


def select_version(branch, published, head="HEAD"):
    pattern = re.compile(re.escape(branch) + r"\.([0-9]+)")
    candidates = [tag for tag in published if pattern.fullmatch(tag)]
    for tag in sorted(candidates, key=lambda tag: int(tag.rsplit(".", 1)[1]), reverse=True):
        ref = f"{NAMESPACE}/tags/{tag}"
        # Upstream branch ancestry excludes releases from another line of development.
        if all(subprocess.run(
            ["git", "merge-base", "--is-ancestor", ref, target], check=False,
        ).returncode == 0 for target in (head, f"{NAMESPACE}/branch")):
            return tag
    raise RuntimeError(f"No published {branch} release is included in {head}; merge upstream first")


def image_exists(image):
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", "--raw", image],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False,
    )
    if result.returncode == 0:
        return True
    if f"{image}: not found" in result.stderr or "manifest unknown" in result.stderr.lower():
        return False
    # Authentication/network failures are not evidence that a version is unpublished.
    raise RuntimeError(f"Cannot check existing image {image}: {result.stderr.strip()}")


def publication_state(version, published, remote_commit, head, image_present=False):
    if version in published:
        if not remote_commit:
            raise RuntimeError(f"Release {version} exists without a Git tag")
        return False, False
    if remote_commit and remote_commit != head:
        raise RuntimeError(
            f"Fork tag {version} already points to {remote_commit}, not {head}. "
            "It may be an imported upstream tag; resolve that collision before publishing. "
            "The workflow will not overwrite it."
        )
    if image_present:
        # Dispatch-only legacy publications have no Git tag or GitHub Release.
        # Preserve their images without assigning the current commit to an old build.
        # A matching Git tag instead means a partially completed new release can resume.
        return False, bool(remote_commit)
    # An existing tag can be left by a partially completed release. Keep its image pin.
    return not bool(remote_commit), True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--upstream", default="Mailu/Mailu")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"), required=False)
    parser.add_argument("--output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args()
    if not args.repository or not args.output:
        parser.error("--repository and --output (or their GitHub environment variables) are required")
    if not re.fullmatch(r"[0-9]{4}\.[0-9]{2}", args.branch):
        parser.error("branch must be a Mailu release line such as 2024.06")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.upstream):
        parser.error("upstream must be owner/repository")

    published = releases(args.upstream)
    # Isolate upstream tags so fork release tags can point to the OIDC-enabled commit.
    subprocess.run([
        "git", "fetch", "--no-tags", f"https://github.com/{args.upstream}.git",
        f"+refs/heads/{args.branch}:{NAMESPACE}/branch",
        f"+refs/tags/{args.branch}.*:{NAMESPACE}/tags/{args.branch}.*",
    ], check=True)
    version = select_version(args.branch, published)
    head = run("git", "rev-parse", "HEAD")
    refs = run("git", "ls-remote", "--tags", "origin",
               f"refs/tags/{version}", f"refs/tags/{version}^{{}}")
    tags = {line.split()[1]: line.split()[0] for line in refs.splitlines()}
    remote_commit = tags.get(f"refs/tags/{version}^{{}}", tags.get(f"refs/tags/{version}"))
    owner = args.repository.split('/')[0].lower()
    image = f"ghcr.io/{owner}/mailu-admin:{version}"
    publish_pinned, release = publication_state(
        version, releases(args.repository), remote_commit, head, image_exists(image)
    )
    values = {
        "mailu_version": args.branch,
        "pinned_mailu_version": version,
        "docker_org": f"ghcr.io/{args.repository.split('/')[0].lower()}",
        "branch": args.branch,
        "deploy": "true",
        "release": str(release).lower(),
        "publish_pinned": str(publish_pinned).lower(),
        "upstream_admin_image": f"ghcr.io/{args.upstream.split('/')[0].lower()}/admin:{version}",
    }
    with Path(args.output).open("a") as output:
        for key, value in values.items():
            print(f"{key}={value}", file=output)
    print(f"Upstream release included in HEAD: {version}; new release: {release}")


if __name__ == "__main__":
    main()
