#!/usr/bin/env python3
"""假測試 lint：以 AST 偵測測試檔中機械可辨的假測試模式。

用法：
  python3 .claude/hooks/test_lint.py <測試檔.py ...>

規則（只檢查名稱以 test 開頭的函式／方法）：
  conditional-assert  斷言全藏在 if 底下且無 else 兜底——條件不成立時測試默默通過
                      （if/else 兩個分支都有斷言、或 else 有 raise/fail/skip 則不算）
  no-assert           整個測試函式沒有任何斷言（assert 敘述、self.assert*、
                      pytest.raises/warns、mock 的 assert_called*、fail() 都算斷言）
  constant-assert     斷言恆真（assert True 等常數斷言）

誤報豁免：在被標記的那一行行尾加 `# testlint: allow`（豁免理由記入 local_test_evidence）。
非 .py 檔跳過並於 stderr 註記。exit 0 = 乾淨；exit 2 = 有發現；exit 1 = 使用錯誤。
"""
import ast
import sys

ALLOW_PRAGMA = "testlint: allow"


def is_assertion(node):
    """assert 敘述、assert* 開頭的呼叫（self.assertEqual、mock.assert_called…）、fail()。"""
    if isinstance(node, ast.Assert):
        return True
    if isinstance(node, ast.Call):
        func = node.func
        name = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        return bool(name) and (name.startswith("assert") or name == "fail")
    if isinstance(node, (ast.With, ast.AsyncWith)):
        # with pytest.raises(...) / self.assertRaises(...) 作 context manager
        for item in node.items:
            expr = item.context_expr
            if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
                if expr.func.attr in {"raises", "warns", "assertRaises", "assertWarns"}:
                    return True
    return False


def contains_assertion(nodes):
    for n in nodes:
        for sub in ast.walk(n):
            if is_assertion(sub):
                return True
    return False


def branch_covered(orelse):
    """else 分支有斷言、raise、skip/fail 呼叫 → 視為有兜底。"""
    if contains_assertion(orelse):
        return True
    for n in orelse:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Raise):
                return True
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                if sub.func.attr in {"skip", "fail", "xfail"}:
                    return True
    return False


def lint_test_func(func, lines, findings, path):
    def allowed(lineno):
        return lineno <= len(lines) and ALLOW_PRAGMA in lines[lineno - 1]

    has_assertion = False
    for node in ast.walk(func):
        if is_assertion(node):
            has_assertion = True
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Constant):
            if node.test.value and not allowed(node.lineno):
                findings.append(
                    (path, node.lineno, "constant-assert", "斷言恆真，無鑑別力")
                )
        if isinstance(node, ast.If):
            if contains_assertion(node.body) and not branch_covered(node.orelse):
                if not allowed(node.lineno):
                    findings.append(
                        (path, node.lineno, "conditional-assert",
                         "斷言藏在 if 底下且無 else 兜底：條件不成立時測試默默通過")
                    )
    if not has_assertion and not allowed(func.lineno):
        findings.append(
            (path, func.lineno, "no-assert", f"測試函式 {func.name} 沒有任何斷言")
        )


def lint_file(path, findings):
    try:
        with open(path, encoding="utf-8") as f:
            source = f.read()
    except OSError as e:
        print(f"[test-lint] {path} 無法讀取（{e}），跳過", file=sys.stderr)
        return
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        findings.append((path, e.lineno or 0, "syntax-error", f"無法解析：{e.msg}"))
        return
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                lint_test_func(node, lines, findings, path)


def main():
    files = sys.argv[1:]
    if not files:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    findings = []
    for path in files:
        if not path.endswith(".py"):
            print(f"[test-lint] {path} 非 Python 檔，跳過（lint 僅支援 .py）", file=sys.stderr)
            continue
        lint_file(path, findings)
    if findings:
        for path, lineno, rule, msg in findings:
            print(f"{path}:{lineno} [{rule}] {msg}")
        print(f"[test-lint] 共 {len(findings)} 個發現", file=sys.stderr)
        sys.exit(2)
    print("[test-lint] PASS: 無假測試模式")


if __name__ == "__main__":
    main()
