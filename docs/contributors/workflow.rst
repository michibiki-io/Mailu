Contribution workflow
=====================

.. _git_workflow:

Forking vs. committing
----------------------

Linus' way of things sounds fine for now: if you find yourself implementing a
new feature, either send me an email with a bunch of commits or use Github
pull request feature. Maybe if the user base grows too much as well as the need
for trust in a specific branch of the project, we can switch to a shared
repository and add a couple of trusted committers.

Commits
-------

This is a community project, thus commits should be readable enough for any of
the contributors to guess the content by simply reading the comment or find a
proper commit when one knows what they are looking for.

Usual standards remain: write English comments, single line short comments and
additional multi-line if required (keep in mind that the most important piece
of information should fit in the first line).

Branches
--------

You are of course free of naming you branches to your taste or even using
master directly if you find this appropriate. Still, keep in mind that:

- a git email or a pull request should address a single feature a bug,
  so keep your branches as tidy as possible;
- this is a small project with a limited number of forks and active threads
  on Github, so someone might want to look at your fork and find the branch you
  are using to implement a specific feature; to avoid any hassle, we suggest
  that you use branch names prefixed with ``feat-`` or ``fix-`` and followed
  either by the name of the Github issue or a short and meaningful name.

PR Workflow
-----------

All pull requests have to be against the main ``master`` branch.
The PR gets build by a Github Action workflow and some primitive auto-testing is done.
Test images get uploaded to a separate section in Docker hub.
Reviewers will check the PR and test the resulting images.
See the :ref:`testing` section for more info.

Urgent fixes can be backported to the stable branch.
For this a member of **Mailu/contributors** has to set the ``type/backport`` label.
Upon merge of the original PR, a copy of the PR is created against the stable branch.
After some testing on master, we will approve and merge this new PR as well.

At the end of every milestone, a new stable branch will be created from ``master``
or any previous commit that matches the completion of the milestone.

CHANGELOG
---------

Adding entries in the CHANGELOG is an automated process which requires creation of a file under
``towncrier/newsfragments`` directory.

The start of the filename is the ticket number, and the content is what will end up in the news file.
For example, if ticket ``#850`` is about adding a new widget, the filename would be towncrier/newsfragments/850.feature
and the content would be ``Feature that has just been added``.

Supported file extensions are:

- ``.feature``: Signifying a new feature.
- ``.bugfix``: Signifying a bug fix.
- ``.doc``: Signifying a documentation improvement.
- ``.removal``: Signifying a deprecation or removal of public API.
- ``.misc``: A ticket has been closed, but it is not of interest to users.

Forked projects
---------------

If you find yourself forking the project for a specific independent purpose
(commercial use, different philosophy or incompatible point of view), we would
be glad if you let us know so that we can list interesting known forks and
their specific features (and backport some of them if your implementation
is free as well).

Fork image workflow
-------------------

Pushes to the fork's ``2024.06`` branch build the admin, nginx, and webmail
images. The workflow selects the latest published ``2024.06.<patch>``
release whose tag is in both the fork commit and upstream release branch.
It uses that upstream version for the admin UI assets and for the services
that still run upstream images.

The first fork release based on ``2024.06.71`` uses ``2024.06.71-r1``
as the Git tag, GitHub Release, and tag for all three fork images. Further
fork releases on that base increment the revision. A new upstream patch
starts at ``r1``. Previously published unqualified tags remain pinned to
their original releases.

The live branch tip can resume publishing its revision. The workflow reuses
existing fixed images only when their revision annotation matches the commit
and their index includes both supported architectures. A newer tip skips
revisions reserved by coherent earlier commits and preserves their artifacts.
The workflow stops when it cannot verify provenance or a tag's image set.
After all three images are verified, it creates the Git tag and GitHub
Release, then promotes the admin aliases ``2024.06`` and ``latest``.
Deploy the subpath images with their fixed tags. See :doc:`../web-subpath`.

Both the base and admin builds support ``linux/amd64`` and ``linux/arm64/v8``
(``linux/arm64`` is also accepted as input). arm/v7 is no longer built or
included in new manifests; a dispatch requesting it fails input validation.
Previously published fixed image tags are preserved under the existing policy.

ARM jobs default to the GitHub-hosted ``ubuntu-24.04-arm`` runner, so arm64
builds run natively. ARM jobs do not fall back to the generic ``ACTIONS_RUNNER``
variable. Optionally set ``ACTIONS_RUNNER_ARM64`` to a Docker-capable native
ARM64 runner label; a different host architecture fails with a diagnostic
instead of silently emulating arm64. Other jobs continue to use
``ACTIONS_RUNNER`` with the existing hosted Ubuntu fallback. Neither supported
platform requires QEMU, and the workflows do not install it.

The workflow uses ``GITHUB_TOKEN`` with explicit ``packages: write`` permission
for GHCR and ``contents: write`` permission for tags and GitHub releases.
Existing packages must grant this repository Actions access. Docker Hub login
secrets (``Docker_Login`` / ``Docker_Password`` and the ARM equivalents ending
in ``2``) are optional and only increase the authenticated pull allowance.

``build-test-deploy`` remains available through manual dispatch for builds.
For an ARM-only build, select ``linux/arm64`` or ``linux/arm64/v8``.
The default assets image is ``ghcr.io/mailu/admin:<pinned_mailu_version>``;
``upstream_admin_image`` overrides it. Manual builds use tags containing the
workflow run ID. A release-branch push or a rerun of that push can publish
fixed and rolling tags while its commit is still the branch tip.

The inherited integration tests are opt-in and require the complete upstream
service image set. The fork build supplies only the three Web UI images.

Pull requests targeting ``2024.06`` and pushes to ``feature/**`` run
``Validate fork workflows``. This read-only workflow checks release-selection
regressions, Bake platform/image plans, publication command arguments, and
workflow syntax; it neither builds final images nor publishes packages.

PR validation also runs ``arm-build-smoke`` on ``ubuntu-24.04-arm``. It verifies
the native host architecture and builds a minimal arm64 image without
publishing anything or registering QEMU. The smoke Dockerfile checks the
architecture reported inside the build stage. Full Mailu image build times are measured by
the release workflow after merge, not by this smoke check.

Workflow JavaScript actions use Node.js 24-compatible majors: checkout v7,
Docker Buildx setup and registry login v4, and retry v4. Self-hosted runner
overrides must support these action runtimes. Owner-name lowercasing uses Bash,
and registry build caches do not require the GitHub runtime-export helper.
