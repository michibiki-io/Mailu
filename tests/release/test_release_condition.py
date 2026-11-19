"""Exercise the checked-in release guard without tags, images or GitHub writes.

This controlled model covers only the boolean/equality/status expression subset
used by the job, including documented implicit success(). It is not a GitHub
scheduler integration test; actionlint separately checks workflow syntax.
"""
import ast
import itertools
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def release_condition():
    workflow = (ROOT / '.github/workflows/build_test_deploy.yml').read_text()
    job = re.search(r'(?ms)^  deploy:\n(.*?)(?=^  [\w-]+:\n|\Z)', workflow).group(1)
    lines = job.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('    if: '):
            value = line.removeprefix('    if: ').strip()
            if value in ('>', '>-', '|', '|-'):
                parts = []
                for continuation in lines[index + 1:]:
                    if not continuation.startswith('      '):
                        break
                    parts.append(continuation.strip())
                value = ' '.join(parts)
            return value
    raise AssertionError('deploy must declare its condition')


def eligible(expression, event, ref, build, arm, tests, cancelled):
    expression = re.sub(r'!(?!=)', ' not ', expression.replace('&&', ' and ').replace('||', ' or '))
    expression = expression.replace('needs.build-arm.result', 'needs.build_arm.result')
    tree = ast.parse(expression.strip(), mode='eval')
    values = {'github.event_name': event, 'github.ref': ref, 'needs.targets.result': 'success',
              'needs.build.result': build, 'needs.build_arm.result': arm, 'needs.tests.result': tests}
    status = {'cancelled': cancelled, 'always': True, 'success': not cancelled
              and all(result == 'success' for result in (build, arm, tests))}

    def name(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return name(node.value) + '.' + node.attr
        raise AssertionError('Unsupported context reference')

    def evaluate(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bool)):
            return node.value
        if isinstance(node, ast.Attribute):
            return values[name(node)]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.args and not node.keywords:
            return status[node.func.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not evaluate(node.operand)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            return (all if isinstance(node.op, ast.And) else any)(evaluate(value) for value in node.values)
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
            return evaluate(node.left) == evaluate(node.comparators[0])
        raise AssertionError('Unsupported workflow expression: ' + ast.dump(node))

    explicit_status = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                          and node.func.id in status for node in ast.walk(tree))
    return bool(evaluate(tree.body)) and (explicit_status or status['success'])


class ReleaseConditionTest(unittest.TestCase):
    def test_checked_in_guard_for_all_publication_outcomes(self):
        condition = release_condition()
        outcomes = ('success', 'failure', 'cancelled', 'skipped')
        for context in itertools.product(('push', 'workflow_dispatch', 'pull_request'),
                                         ('refs/heads/2024.06', 'refs/heads/feature/example'),
                                         outcomes, outcomes, outcomes, (False, True)):
            event, ref, build, arm, tests, cancelled = context
            allowed = (event == 'push' and ref == 'refs/heads/2024.06' and build == arm == 'success'
                       and tests in ('success', 'skipped') and not cancelled)
            with self.subTest(context=context):
                self.assertEqual(eligible(condition, *context), allowed)


if __name__ == '__main__':
    unittest.main()
