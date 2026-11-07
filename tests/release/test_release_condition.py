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
    job = re.search(r'(?ms)^  tag-release:\n(.*?)(?=^  [\w-]+:\n|\Z)', workflow).group(1)
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
    raise AssertionError('tag-release must declare its condition')


def eligible(expression, release, deploy, workflow_cancelled, ancestor_skipped):
    if expression.startswith('${{') and expression.endswith('}}'):
        expression = expression[3:-2].strip()
    expression = re.sub(r'!(?!=)', ' not ', expression.replace('&&', ' and ').replace('||', ' or '))
    tree = ast.parse(expression.strip(), mode='eval')
    values = {'inputs.release': release, 'needs.deploy.result': deploy}
    status = {'cancelled': workflow_cancelled, 'always': True,
              'success': deploy == 'success' and not ancestor_skipped and not workflow_cancelled,
              'failure': deploy == 'failure'}

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
        # Only successful, requested publication in a non-cancelled run may release.
        # Optional ancestors may either have succeeded or have been skipped.
        allowed = {('true', 'success', False, False), ('true', 'success', False, True)}
        contexts = itertools.product(('true', 'false'), ('success', 'failure', 'cancelled', 'skipped'),
                                     (False, True), (False, True))
        for context in contexts:
            with self.subTest(release=context[0], deploy=context[1], cancelled=context[2], ancestor_skipped=context[3]):
                self.assertEqual(eligible(condition, *context), context in allowed)

    def test_legacy_guard_reproduces_skipped_ancestor_regression(self):
        legacy = "inputs.release == 'true'"
        self.assertTrue(eligible(legacy, 'true', 'success', False, False))
        self.assertFalse(eligible(legacy, 'true', 'success', False, True))
        self.assertTrue(eligible(release_condition(), 'true', 'success', False, True))


if __name__ == '__main__':
    unittest.main()
