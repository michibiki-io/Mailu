"""Exercise revision selection and publication order without registry writes."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/release'))
import fork_release as release

BASE = '2024.06.71'
HEAD = 'a' * 40
PREVIOUS = 'b' * 40
IMAGES = tuple(f'ghcr.io/fork/{component}' for component in release.COMPONENTS)


class ForkReleaseTest(unittest.TestCase):
    def plan(self, published, tags=None, releases=None, upstream=BASE):
        names = {image: set() for image in IMAGES}
        revisions = {}
        for tag, images, owner in published:
            for image in images:
                names[image].add(tag)
                revisions[f'{image}:{tag}'] = owner
        return release.choose_revision(upstream, HEAD, names, tags or {}, releases or {}, revisions.__getitem__)

    def test_legacy_tags_do_not_take_a_fork_revision(self):
        self.assertEqual(self.plan([(BASE, IMAGES[:1], PREVIOUS)], {BASE: PREVIOUS}, {BASE: True}),
                         release.ReleasePlan(f'{BASE}-r1', IMAGES))

    @patch.object(release, 'is_ancestor', return_value=True)
    def test_new_head_skips_every_coherent_earlier_stage(self, ancestor):
        tag = f'{BASE}-r1'
        for images, tags, releases in ((IMAGES[:1], {}, {}), (IMAGES, {}, {}),
                                       (IMAGES, {tag: PREVIOUS}, {}),
                                       (IMAGES, {tag: PREVIOUS}, {tag: True})):
            with self.subTest(images=images, tags=tags, releases=releases):
                self.assertEqual(self.plan([(tag, images, PREVIOUS)], tags, releases),
                                 release.ReleasePlan(f'{BASE}-r2', IMAGES))

    def test_revision_starts_at_one_after_upstream_update(self):
        self.assertEqual(self.plan([(f'{BASE}-r8', IMAGES, PREVIOUS)], upstream='2024.06.72'),
                         release.ReleasePlan('2024.06.72-r1', IMAGES))

    def test_resume_partial_publication_for_live_commit(self):
        tag = f'{BASE}-r1'
        self.assertEqual(self.plan([(tag, IMAGES[:1], HEAD)]), release.ReleasePlan(tag, IMAGES[1:]))
        self.assertEqual(self.plan([(tag, IMAGES, HEAD)], {tag: HEAD}),
                         release.ReleasePlan(tag, (), tagged=True))
        self.assertEqual(self.plan([(tag, IMAGES, HEAD)], {tag: HEAD}, {tag: True}),
                         release.ReleasePlan(tag, (), tagged=True, released=True))

    def test_conflicting_provenance_stops_publication(self):
        tag = f'{BASE}-r1'
        with self.assertRaisesRegex(RuntimeError, 'Conflicting'):
            self.plan([(tag, IMAGES[:1], HEAD), (tag, IMAGES[1:], PREVIOUS)])
        with self.assertRaisesRegex(RuntimeError, 'Incomplete'):
            self.plan([(tag, IMAGES[:1], HEAD)], {tag: HEAD})

    @patch.object(release, 'run')
    def test_superseded_run_returns_before_listing_or_writing(self, run):
        run.return_value = f'{PREVIOUS}\trefs/heads/2024.06'
        env = dict(GITHUB_EVENT_NAME='push', GITHUB_REF='refs/heads/2024.06', GITHUB_REPOSITORY='fork/Mailu',
                   UPSTREAM_VERSION=BASE, GITHUB_SHA=HEAD)
        with patch.dict(release.os.environ, env, clear=True):
            release.main()
        run.assert_called_once_with('git', 'ls-remote', 'origin', 'refs/heads/2024.06')

    @patch.object(release, 'run')
    @patch.object(release, 'require_live_head')
    @patch.object(release, 'inspect_revision')
    def test_incomplete_publication_has_no_aliases_or_git_writes(self, inspect, live, run):
        tag = f'{BASE}-r1'
        run.side_effect = ['created nginx', RuntimeError('push failed')]
        with self.assertRaisesRegex(RuntimeError, 'push failed'):
            release.publish_images(HEAD, release.ReleasePlan(tag, IMAGES[1:]), '7', IMAGES)
        for command in run.call_args_list:
            args = command.args
            self.assertEqual(args[:4], ('docker', 'buildx', 'imagetools', 'create'))
            self.assertTrue(args[7].endswith(f':{tag}'))
        inspect.assert_not_called()

    @patch.object(release, 'run')
    @patch.object(release, 'require_live_head')
    def test_aliases_only_follow_tag_and_release(self, live, run):
        tag = f'{BASE}-r1'
        release.publish_release('fork/Mailu', HEAD, BASE, release.ReleasePlan(tag, ()), IMAGES)
        calls = [call.args for call in run.call_args_list]
        self.assertEqual(calls[0][:3], ('git', 'push', 'origin'))
        self.assertEqual(calls[1][:4], ('gh', 'release', 'create', tag))
        self.assertEqual(calls[2][-5:], ('--tag', f'{IMAGES[0]}:2024.06', '--tag',
                                        f'{IMAGES[0]}:latest', f'{IMAGES[0]}:{tag}'))
        run.reset_mock()
        release.publish_release('fork/Mailu', HEAD, BASE,
                                release.ReleasePlan(tag, (), tagged=True, released=True), IMAGES)
        run.assert_called_once()
        self.assertEqual(run.call_args.args, calls[2])
