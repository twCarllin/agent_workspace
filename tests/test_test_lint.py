"""test_lint.py 的假測試模式偵測測試。

執行：python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import test_lint  # noqa: E402


def lint_source(source):
    import ast
    findings = []
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                test_lint.lint_test_func(node, lines, findings, "mem.py")
    return findings


def rules(findings):
    return [f[2] for f in findings]


class ConditionalAssertTest(unittest.TestCase):
    def test_if_guard_hiding_assert_is_flagged(self):
        findings = lint_source(
            "def test_x():\n"
            "    r = compute()\n"
            "    if r.ok:\n"
            "        assert r.value == 1\n"
        )
        self.assertIn("conditional-assert", rules(findings))

    def test_if_else_both_asserting_passes(self):
        findings = lint_source(
            "def test_x():\n"
            "    if mode:\n"
            "        assert a == 1\n"
            "    else:\n"
            "        assert a == 2\n"
        )
        self.assertNotIn("conditional-assert", rules(findings))

    def test_else_with_fail_passes(self):
        findings = lint_source(
            "def test_x():\n"
            "    if mode:\n"
            "        assert a == 1\n"
            "    else:\n"
            "        pytest.fail('unexpected mode')\n"
        )
        self.assertNotIn("conditional-assert", rules(findings))

    def test_skip_guard_without_assert_not_flagged(self):
        findings = lint_source(
            "def test_x():\n"
            "    if not has_db:\n"
            "        pytest.skip('no db')\n"
            "    assert query() == 1\n"
        )
        self.assertNotIn("conditional-assert", rules(findings))

    def test_pragma_suppresses(self):
        findings = lint_source(
            "def test_x():\n"
            "    if r.ok:  # testlint: allow\n"
            "        assert r.value == 1\n"
        )
        self.assertNotIn("conditional-assert", rules(findings))


class NoAssertTest(unittest.TestCase):
    def test_no_assertion_is_flagged(self):
        findings = lint_source("def test_x():\n    run()\n")
        self.assertIn("no-assert", rules(findings))

    def test_plain_assert_counts(self):
        findings = lint_source("def test_x():\n    assert f() == 1\n")
        self.assertEqual(rules(findings), [])

    def test_unittest_style_counts(self):
        findings = lint_source("def test_x(self):\n    self.assertEqual(f(), 1)\n")
        self.assertEqual(rules(findings), [])

    def test_pytest_raises_counts(self):
        findings = lint_source(
            "def test_x():\n"
            "    with pytest.raises(ValueError):\n"
            "        f(-1)\n"
        )
        self.assertEqual(rules(findings), [])

    def test_mock_assert_called_counts(self):
        findings = lint_source("def test_x():\n    m.assert_called_once_with(1)\n")
        self.assertEqual(rules(findings), [])

    def test_non_test_function_ignored(self):
        findings = lint_source("def helper():\n    run()\n")
        self.assertEqual(findings, [])


class ConstantAssertTest(unittest.TestCase):
    def test_assert_true_is_flagged(self):
        findings = lint_source("def test_x():\n    assert True\n")
        self.assertIn("constant-assert", rules(findings))

    def test_real_assert_not_flagged(self):
        findings = lint_source("def test_x():\n    assert f() is True\n")
        self.assertNotIn("constant-assert", rules(findings))


if __name__ == "__main__":
    unittest.main()
