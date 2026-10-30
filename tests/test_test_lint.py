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
        self.assertNotIn("no-assert", rules(findings))

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


class WarnRulesTest(unittest.TestCase):
    """警示規則只列印、不計入 exit code（test-strategy「測試取捨」）。"""

    def test_message_literal_and_internal_coupling_are_warnings(self):
        findings = lint_source(
            "def test_x():\n"
            "    self.assertIn('假測試 lint 未過，請修測試或以行尾豁免並留痕', out)\n"
            "    self.assertEqual(code, 2)\n"
            "    self.assertEqual(mod._state, 1)\n"
            "    spy.assert_called_once()\n"
            "    self._helper()\n"
        )
        self.assertEqual(rules(findings).count("message-literal"), 1)
        self.assertEqual(rules(findings).count("internal-coupling"), 2)
        self.assertTrue(set(rules(findings)) <= test_lint.WARN_RULES)

    def test_pragma_suppresses_warning(self):
        findings = lint_source(
            "def test_x():\n"
            "    self.assertIn('假測試 lint 未過，請修測試或以行尾豁免並留痕', out)  # testlint: allow\n"
        )
        self.assertEqual(rules(findings), [])

    def test_cli_exit_zero_with_only_warnings(self):
        import subprocess, sys as _sys, tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as tmp:
            f = _P(tmp) / "test_w.py"
            f.write_text(
                "def test_x():\n"
                "    assert mod._state == 1\n"
                "    mod._state\n"
            )
            r = subprocess.run(
                [_sys.executable, str(_P(test_lint.__file__)), str(f)],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0)
            self.assertIn("[warn internal-coupling]", r.stdout)
