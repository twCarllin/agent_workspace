#!/usr/bin/env python3
"""subagent 報告信封機械驗收。

用途：PostToolUse hook——subagent（Task/Agent tool）交付完成後，機械檢查其
報告信封是否合規（首行戳記行、末行恰一個 Self-check:；task-verifier 另加驗
「完成度」「憑據」兩節關鍵詞）。

性質：品質 lint，不是安全 gate。fail-open——stdin 非 JSON、頂層非 dict、
欄位型別不符等一切解析異常一律放行（exit 0），只有「payload 結構正常且能
抽出報告文字，但信封本身不合規」才 exit 2 退件。

載荷依據：2026-09-07 以臨時 dump hook 實測 PostToolUse 的 stdin 載荷格式
（見 run/2026-09-07-report-envelope-hook.json spec_inline）：
  tool_name: "Task" 或 "Agent"
  tool_input: {"subagent_type": str, "run_in_background": bool（可能缺席）}
  tool_response: {"status": str, "content": [{"type": "text", "text": str}, ...]}
  背景啟動時 tool_response 是啟動回執（status 非 "completed" 或無 content
  text），非交付報告。

exit 0 = 放行（不驗或驗過）；exit 2 = 信封缺損，stderr 附退件訊息。
"""
import json
import re
import sys

# 需驗信封的 subagent 名單（三循環 agent 定義皆載信封規則）
ENVELOPE_AGENTS = {
    "code-writer",
    "code-reviewer",
    "task-verifier",
    "retro",
    "impact-analyzer",
    "usage-analyzer",
    "task-decomposer",
}

STAMP_RE = re.compile(r"^\* _\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(.+\)_\s*$")


def extract_report_text(tool_response):
    """從 tool_response 抽出報告全文（所有 type=="text" block 的 text 以換行
    join）；抽不到（無 text block 或空字串）回傳 None。"""
    content = tool_response.get("content")
    if not isinstance(content, list):
        return None
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                texts.append(text)
    joined = "\n".join(texts)
    return joined if joined.strip() else None


def check_envelope(text, subagent_type):
    """驗信封，回傳缺項清單（list[str]）；全部合規回傳空 list。"""
    missing = []
    lines = [line for line in text.splitlines() if line.strip() != ""]

    # 戳記行落在前 3 個非空行內即合規：容忍 harness 在戳記行前自動插入的
    # byline／日期行（實測 agent 框架前插 1–2 行，令「首行必為戳記」永遠假陽性）。
    # 前 3 個非空行皆非戳記行（戳記在更後或全無）才退件。
    if not any(STAMP_RE.match(line) for line in lines[:3]):
        missing.append("首行戳記行")

    self_check_idxs = [i for i, line in enumerate(lines) if line.startswith("Self-check:")]
    if len(self_check_idxs) != 1 or self_check_idxs[0] != len(lines) - 1:
        missing.append("Self-check 終行")

    if subagent_type == "task-verifier":
        if "完成度" not in text or "憑據" not in text:
            missing.append("兩節關鍵詞（完成度／憑據）")

    return missing


def main():
    raw = sys.stdin.read()

    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            sys.exit(0)

        if payload.get("tool_name") not in ("Task", "Agent"):
            sys.exit(0)

        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            sys.exit(0)

        subagent_type = tool_input.get("subagent_type")
        if subagent_type not in ENVELOPE_AGENTS:
            sys.exit(0)

        if tool_input.get("run_in_background") is True:
            sys.exit(0)

        tool_response = payload.get("tool_response")
        if not isinstance(tool_response, dict):
            sys.exit(0)

        status = tool_response.get("status")
        if status is not None and status != "completed":
            sys.exit(0)

        report_text = extract_report_text(tool_response)
        if not report_text:
            sys.exit(0)
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        sys.exit(0)

    missing = check_envelope(report_text, subagent_type)
    if missing:
        print(
            f"[report-envelope] 信封缺損（{subagent_type}）："
            f"{'、'.join(missing)}。退件重取：重新呼叫該 subagent 補齊信封"
            f"（首行戳記行、末行恰一個 Self-check:）。",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
