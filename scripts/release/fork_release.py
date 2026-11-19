#!/usr/bin/env python3
"""Publish the fork's matching Web UI image set and GitHub release."""
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from upstream_version import run


COMPONENTS = ("mailu-admin", "mailu-nginx", "mailu-webmail")
PLATFORMS = {("linux", "amd64"), ("linux", "arm64")}
BRANCH = "2024.06"
REVISION_KEY = "org.opencontainers.image.revision"
SHA = re.compile(r"[0-9a-f]{40}")


def require_live_head(head):
    if run("git", "ls-remote", "origin", f"refs/heads/{BRANCH}").split() != [
        head, f"refs/heads/{BRANCH}"
    ]:
        raise Superseded(f"Skipping release publication for superseded commit {head}")


class Superseded(RuntimeError):
    pass


def is_ancestor(earlier, head):
    result = subprocess.run(["git", "merge-base", "--is-ancestor", earlier, head], check=False)
    return result.returncode == 0


def registry_json(url, authorization):
    with urlopen(Request(url, headers={"Authorization": authorization}), timeout=30) as response:
        return json.load(response), response.headers.get("Link", "")


def registry_tags(image):
    repository = image.removeprefix("ghcr.io/")
    credentials = f'{os.environ["GITHUB_ACTOR"]}:{os.environ["GH_TOKEN"]}'
    basic = base64.b64encode(credentials.encode()).decode()
    query = urlencode({"service": "ghcr.io", "scope": f"repository:{repository}:pull"})
    token, _ = registry_json(f"https://ghcr.io/token?{query}", f"Basic {basic}")
    path = f"/v2/{repository}/tags/list"
    url = f"https://ghcr.io{path}?n=100"
    while url:
        page, link = registry_json(url, f'Bearer {token["token"]}')
        if page["name"] != repository:
            raise RuntimeError(f"Registry returned tags for an unexpected repository: {page['name']}")
        yield from page["tags"] or []
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        if link and not match:
            raise RuntimeError(f"Unexpected registry pagination for {image}")
        url = urljoin(url, match[1]) if match else ""
        if url:
            target = urlsplit(url)
            if (target.scheme, target.netloc, target.path) != ("https", "ghcr.io", path):
                raise RuntimeError(f"Unexpected registry pagination target for {image}")


def inspect_revision(image):
    manifest = json.loads(run("docker", "buildx", "imagetools", "inspect", "--raw", image))
    revision = manifest.get("annotations", {}).get(REVISION_KEY, "")
    descriptors = manifest.get("manifests", ())
    platforms = {(d.get("platform", {}).get("os"), d.get("platform", {}).get("architecture"))
                 for d in descriptors}
    if not SHA.fullmatch(revision) or platforms != PLATFORMS or len(descriptors) != len(PLATFORMS):
        raise RuntimeError(f"Cannot verify revision and platforms for {image}")
    return revision


def tag_commits():
    prefix = "refs/tags/"
    refs = {}
    for line in run("git", "ls-remote", "--tags", "origin").splitlines():
        commit, ref = line.split()
        refs[ref.removeprefix(prefix)] = commit
    return {tag: refs.get(tag + "^{}", commit) for tag, commit in refs.items()
            if not tag.endswith("^{}")}


def release_states(repository):
    releases = run("gh", "api", "--paginate", f"repos/{repository}/releases?per_page=100",
                   "--jq", '.[] | [.tag_name, (.draft or .prerelease)] | @tsv')
    return {tag: partial == "false" for tag, partial in
            (entry.split("\t") for entry in releases.splitlines())}


@dataclass(frozen=True)
class ReleasePlan:
    tag: str
    missing: tuple
    tagged: bool = False
    released: bool = False


def choose_revision(upstream, head, image_tags, tags, releases, inspect=inspect_revision):
    pattern = re.compile(re.escape(upstream) + r"-r([1-9][0-9]*)")
    occupied = set(tags) | set(releases)
    for published in image_tags.values():
        occupied.update(published)
    revisions = sorted((int(match[1]), name) for name in occupied
                       if (match := pattern.fullmatch(name)))
    matching = []
    for _, tag in revisions:
        present = [image for image, names in image_tags.items() if tag in names]
        owners = {inspect(f"{image}:{tag}") for image in present}
        tagged = tag in tags
        released = tag in releases
        complete = len(present) == len(COMPONENTS)
        if (released and (not releases[tag] or not tagged)) or (tagged and not complete):
            raise RuntimeError(f"Incomplete or unexpected GitHub metadata for {tag}")
        if tagged:
            owners.add(tags[tag])
        if len(owners) != 1:
            raise RuntimeError(f"Conflicting image or Git provenance for {tag}")
        owner, = owners
        if owner == head:
            matching.append(ReleasePlan(tag, tuple(image for image in image_tags
                                                   if image not in present), tagged, released))
        elif not is_ancestor(owner, head):
            raise RuntimeError(f"{tag} belongs to {owner}, which is not an ancestor of {head}")
    if len(matching) > 1:
        raise RuntimeError(f"More than one revision is reserved by {head}")
    if matching:
        return matching[0]
    next_revision = revisions[-1][0] + 1 if revisions else 1
    return ReleasePlan(f"{upstream}-r{next_revision}", tuple(image_tags))


def publish_images(head, plan, run_id, images):
    for image in plan.missing:
        require_live_head(head)
        fixed = f"{image}:{plan.tag}"
        build_tag = f"{image}:{BRANCH}-build-{run_id}"
        run("docker", "buildx", "imagetools", "create",
            "--annotation", f"index:{REVISION_KEY}={head}", "--tag", fixed,
            build_tag, build_tag + "-arm")
    for image in images:
        fixed = f"{image}:{plan.tag}"
        if inspect_revision(fixed) != head:
            raise RuntimeError(f"{fixed} does not match the release commit")


def release_notes(upstream, head, tag, images):
    references = "\n".join(f"- `{image}:{tag}`" for image in images)
    return f"""Based on [Mailu {upstream}](https://github.com/Mailu/Mailu/releases/tag/{upstream}).
Fork commit: `{head}`.

The following images ship as a set for Linux amd64 and arm64:

{references}

Set the official Helm chart's `mailuVersion` to `{upstream}` and override the
repositories and tags of front, admin, and webmail using the references above.
Set `WEB_BASE_PATH` through each component's `extraEnvVars` to enable a
subpath. Use upstream `{upstream}` images for the other Mailu components.

For rollback, restore all three image references, `mailuVersion`, the ingress,
the OIDC callback registration, and the environment from the previous deployment.
See [deployment examples](https://github.com/michibiki-io/Mailu/blob/{head}/docs/web-subpath.rst).
"""


def publish_release(repository, head, upstream, plan, images):
    if not plan.tagged:
        require_live_head(head)
        run("git", "push", "origin", f"{head}:refs/tags/{plan.tag}")
    if not plan.released:
        require_live_head(head)
        with tempfile.TemporaryDirectory() as directory:
            notes = Path(directory) / "release.md"
            notes.write_text(release_notes(upstream, head, plan.tag, images), encoding="utf-8")
            run("gh", "release", "create", plan.tag, "--repo", repository, "--verify-tag", "--latest",
                "--title", plan.tag, "--notes-file", str(notes))
    require_live_head(head)
    admin = images[0]
    run("docker", "buildx", "imagetools", "create", "--tag", f"{admin}:{BRANCH}",
        "--tag", f"{admin}:latest", f"{admin}:{plan.tag}")


def main():
    if os.environ["GITHUB_EVENT_NAME"] != "push" or os.environ["GITHUB_REF"] != f"refs/heads/{BRANCH}":
        raise RuntimeError("Only a push to the release branch can publish a fork release")
    repository = os.environ["GITHUB_REPOSITORY"]
    upstream = os.environ["UPSTREAM_VERSION"]
    head = os.environ["GITHUB_SHA"]
    if not re.fullmatch(re.escape(BRANCH) + r"\.[0-9]+", upstream) or not SHA.fullmatch(head):
        raise ValueError("Invalid upstream version or source commit")
    images = tuple(f"ghcr.io/{repository.split('/')[0].lower()}/{name}" for name in COMPONENTS)
    try:
        require_live_head(head)
        plan = choose_revision(upstream, head, {image: set(registry_tags(image)) for image in images},
                               tag_commits(), release_states(repository))
        print(f"Publishing {plan.tag} from {head}")
        publish_images(head, plan, os.environ["GITHUB_RUN_ID"], images)
        publish_release(repository, head, upstream, plan, images)
    except Superseded as exc:
        print(exc)


if __name__ == "__main__":
    main()
