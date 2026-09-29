# Spec — subagent 派工改走 headless CLI（`claude -p` 預設、`codex exec` 備選）

- **run_id**：`2026-09-29-headless-dispatch`
- **建立**：2026-09-29
- **來源**：使用者要求「按照現在的程式碼，再加一個修改：執行都請用 `claude -p` 或是 `codex exec`」。經釐清（2026-09-29 裁示）：改的是 **subagent 派工層**——主 flow 呼叫 code-writer／task-verifier 等流程角色時，不再用 Claude Code 的 `Agent` 工具或 Codex custom agent，改以子程序執行 headless CLI；**預設 `claude -p`**，`codex exec` 為備選後端。

---

## §1 問題陳述

現行 eval-flow 的派工路徑是 harness 內建的 `Agent`（Task）工具：主 flow 以 `subagent_type` 指名角色，harness 在同一 session 內開子 agent。這條路徑的三個依附點：

1. **gate**：`.claude/hooks/eval_gates.py` 的 phase 狀態機只攔 `tool_name ∈ {Task, Agent}` 的呼叫（`check_task_gate`）。
2. **信封 lint**：`.claude/hooks/report_envelope_check.py` 掛在 PostToolUse `Task|Agent`，讀 `tool_response.content[].text`。
3. **token 實測**：`.claude/hooks/token_usage.py` 從主 session transcript 同層的 `<session_id>/subagents/agent-*.jsonl` 加總子 agent 用量。

使用者要求派工改為子程序執行 `claude -p`（或 `codex exec`）。三個依附點都以「Agent 工具」為前提，派工換路徑後全部落空：gate 不攔、信封不驗、用量不計。本 Spec 定義新的派工機制與三個依附點的對應改法。

## §2 已裁示的決策（使用者，2026-09-29）

| # | 決策 | 內容 |
|---|---|---|
| D1 | 改動範圍 | 只改 **subagent 派工層**。parallel-run 與 Tier 2 [P] fan-out 的 worktree 背景 agent（`Agent isolation: "worktree"`）**不在本次範圍**，維持原機制 |
| D2 | 後端選用 | **預設 `claude -p`**；`codex exec` 為備選。無旗標時：manifest `harness` 為 `"codex"` → codex，否則 claude；`--backend` 旗標覆蓋 |
| D3 | 子 session 權限 | **全放行**：`claude -p` 帶 `--dangerously-skip-permissions`；`codex exec` 帶 `--dangerously-bypass-approvals-and-sandbox`。逐角色白名單方案已提出、使用者否決 |
| D4 | 舊路徑處置 | **不擋**：`Agent` 工具呼叫流程角色仍合法；文件改為要求走派工 script，hook 不新增阻擋 |
| D5 | 進場 dirty tree | `run/gate_hits.log`、`run/tier0.jsonl` 擱置不動，不納入本 run |

## §3 目標狀態

### 3.1 派工 script：`.claude/hooks/dispatch.py`（新增）

```
python3 .claude/hooks/dispatch.py <role> --prompt-file <path> [--backend claude|codex] [--resume <session_id>]
```

- `<role>`：`.claude/agents/<role>.md` 存在者（code-writer／code-reviewer／task-verifier／retro／task-decomposer／usage-analyzer／impact-analyzer）。不存在 → exit 1、stderr 說明。
- `--prompt-file`：派工 prompt 全文（主 flow 已組裝好硬性約束區、契約表原文等；`-` 表 stdin）。**約定路徑** `run/<run_id>.prompt-<role>-<n>.md`（冷溯源檔，留工作目錄、不進版控；`MANIFEST_RE` 只認 `run/*.json`，`.md` 不受 gate 影響）。
- **claude 後端**（預設）：執行 `claude -p --agent <role> --output-format json --dangerously-skip-permissions [--resume <sid>]`，prompt 由 stdin 餵入。`--agent` 令 headless session 載入 `.claude/agents/<role>.md` 的 system prompt、frontmatter `model` 與 `tools`（2026-09-29 實測：`--agent task-verifier` 回報 model `claude-haiku-4-5-20251001`、系統提示為該檔正文），故 `MODEL_POLICY.md` 仍是 model 單一枚舉點、agent 定義檔不需改。
- **codex 後端**：執行 `codex exec --json --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox -m <model> -c model_reasoning_effort=<effort>`；`<model>`／`<effort>` 讀 `.codex/agents/<role>.toml`（`install_codex.py` 產生）；stdin 餵 `developer_instructions` ＋ 空行分隔 ＋ prompt 全文（`codex exec` 無 `--agent` 對應旗標，角色指令由 script 併入）。`--resume <thread_id>` 對應 `codex exec resume <thread_id> --json`。
- **輸出契約**：
  - stdout ＝ 子 agent 的**報告全文**（claude：JSON `result` 欄；codex：最後一個 `item.completed` 且 `item.type == "agent_message"` 的 `text`），不夾雜其他行——主 flow 直接讀。
  - stderr ＝ 一行摘要 `[dispatch] role=<role> backend=<b> session=<sid> turns=<n> tokens=<四欄合計> cost_usd=<c|n/a>`，主 flow 憑 `session` 值做修正輪 `--resume`。
  - exit code：子程序失敗（非 0 exit、JSON `is_error: true`、解析不到報告）→ exit 3、stderr 附原因；信封 blocking → exit 2（同下）；其餘 0。
- **信封驗收內建**：對報告全文呼叫 `report_envelope_check.check_envelope(text, role)`（重用單一判定點）。blocking → stderr 印與 hook 同款退件訊息、exit 2（報告仍完整輸出到 stdout，供第 2 次缺損時人工檢視）；advisory → stderr 警告、exit 0。`.claude/settings.json` 的 PostToolUse hook 保留（D4：Agent 工具路徑仍合法）。
- **用量留痕**：每次派工 append 一行到 `run/<run_id>.dispatch.jsonl`（冷溯源檔，格式見 §3.4）。run_id 解析沿用 `eval_gates.py` 既有基準（R-009）：`eval_state.json` 的 `run_id`，否則 `_find_unique_tier1_inprogress()`；兩者皆無（run 外的手動觸發）→ 不落檔、stderr 一句說明、不改 exit code（旁路不得變主路，同 `append_event` 慣例）。
- 子程序在**當前 cwd** 執行（worktree 內派工即在該 worktree）；不改環境變數。

### 3.2 gate：`eval_gates.py` 對 Bash 派工指令套用同一 phase 狀態機

- `run_hook()` 對 `tool_name == "Bash"` 的 `command` 以 regex 辨識 `dispatch.py <role>`（role 為 `dispatch.py` 後第一個非旗標 token；旗標可在 role 前後）→ 以該 role 呼叫既有 `check_task_gate`（`AGENT_MIN_PHASE` 不變：code-writer 需 `decomposed`＋`task_file`，其餘 `init`；非流程角色放行）。
- 順序：派工辨識在 `git commit` 辨識之前；一條指令不會同時是兩者。
- `Task|Agent` 路徑原樣保留（D4）。

### 3.3 token 實測：`token_usage.py` 併入派工留痕

- 讀 `run/<run_id>.dispatch.jsonl`（不存在＝零筆），每行轉成 `subagents` 清單一筆：`agent_type = role`、`description = "dispatch:<backend>"`、四欄＋`turns`。與既有 transcript `subagents/` 目錄來源**聯集**（同一 run 兩種派工混用時兩邊都計）。
- `prep`／`loop` 分類與 `--write` 回寫 `subagent_usage`／`token_usage` 規則不變（`PREP_AGENT_TYPES` 沿用）。
- 派工留痕不受 events 時間窗切割（留痕本身就是 per-run）。
- `harness: "codex"` 的主 run 早退路徑（`unknown_codex`）**不變**——本次不擴 Codex 主 session 計量。

### 3.4 新冷溯源檔：`run/<run_id>.dispatch.jsonl`

每行 JSON：

```json
{"ts": "<ISO8601 UTC>", "role": "code-writer", "backend": "claude", "session_id": "<sid|thread_id>",
 "resumed": false, "model": "<modelUsage 首鍵|toml model>", "turns": 3,
 "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 0,
 "cost_usd": 0.0, "duration_ms": 0, "exit_code": 0, "envelope": "ok|advisory|blocking"}
```

- codex 用量欄位映射：`input_tokens`→`input_tokens`、`cached_input_tokens`→`cache_read_input_tokens`、`cache_write_input_tokens`→`cache_creation_input_tokens`、`output_tokens`→`output_tokens`；`cost_usd` 為 `null`（codex 不回報）。
- 純記錄檔，不被任何 gate 消費（加 gate 消費即為判定行為變更，比照 `verification_commands` 條款）。消費端：`token_usage.py`。

### 3.5 文件同步（單一枚舉點原則，R-007）

| 文件 | 變更 |
|---|---|
| `skills/eval-flow/SKILL.md` | 新增「派工機制」節（指令、prompt 檔約定、修正輪 `--resume`、信封由 script 內建驗收）；循環 step 1／3、前置 1、具名問題觸發、step 7 的「呼叫 X subagent」措辭改為指向該節；「Subagent 呼叫原則」的背景執行／auto-mode 段補一句：headless 派工為前景子程序、權限依 D3 全放行，`run_in_background` 條款只對仍走 Agent 工具的呼叫有效；step 6 ②之前的 token_usage 說明補「含派工留痕」 |
| `skills/eval-flow/references/gates.md` | gate 7 補「Bash `dispatch.py <role>` 同受本 gate」；信封 lint 節補「派工 script 內建同一判定」 |
| `skills/eval-flow/references/formats.md` | 新增 `run/<run_id>.dispatch.jsonl` 格式節；`token_usage` 欄語義補來源聯集 |
| `CODEX_ADAPTER.md` | 「Claude `Task`／`Agent`」列改為 `dispatch.py --backend codex`（`codex exec`），custom agent toml 改為 model／instructions 的來源 |
| `README.md` | 檔案地圖表加一列 `.claude/hooks/dispatch.py` |
| `CLAUDE.md` Task Principle | 「呼叫 subagent 完成任務」補「（經 `.claude/hooks/dispatch.py`，見 eval-flow skill）」 |
| `MODEL_POLICY.md` | 檔頭補一句：headless 派工以 `--agent` 讀同一 frontmatter，本表仍為單一枚舉點 |
| `.claude/hooks/doctor.py` | `HOOKS` 清單加 `dispatch.py`（部署健檢） |
| `TODO.md` 第 11 節 | 補一行：派工層已改 headless（本 run），driver 的 session-per-worktree 可重用 `dispatch.py` |

## §4 不變量（不得弱化）

- `MODEL_POLICY.md` ↔ frontmatter 一致性測試不變；agent 定義檔正文不改。
- `AGENT_MIN_PHASE`、`check_task_gate` 判定內容不變，只新增觸發入口。
- `MANIFEST_RE` 單一判定點不變；新檔案 `*.dispatch.jsonl`／`*.prompt-*.md` 不匹配該 pattern，無需改 pattern。
- 信封判定單一出處為 `report_envelope_check.check_envelope`，dispatch 不自建第二份規則。
- `init.sh`／`install_codex.py` 以 glob 複製 `.claude/hooks/*.py`，新 script 自動隨部署，不改安裝器。

## §5 開放問題與已知限制

- **Q1（已知限制，接受）**：headless 子 session 是獨立 session，其 transcript 落在 `~/.claude/projects/<cwd>/<new_sid>.jsonl`，不在主 session 的 `subagents/` 目錄；用量改由 JSON 結果回寫 `dispatch.jsonl`，精度等同（同為 API usage 四欄）。
- **Q2（已知限制，接受）**：codex 後端的 `cost_usd` 不可得，記 `null`；`stats.py` 只消費 token 數，不受影響。
- **Q3（範圍外）**：parallel-run／fan-out 的 worktree 背景 agent 仍走 `Agent isolation: "worktree"`（D1）。TODO 第 11 節的 driver 若日後動工，`dispatch.py` 可直接作為 session-per-worktree 的啟動器。
- **Q4（範圍外）**：`--max-turns`／`--max-budget-usd` 護欄本次不加；子 session 無上限。

## §6 驗收（R-005：跨進程執行契約須有真實端到端證據）

- 自動化測試以 PATH 上的假 `claude`／`codex` 可執行檔驗 argv、stdin、stdout、留痕逐鍵（R-004）。
- **另須一次真實執行**：以 `dispatch.py task-verifier`（haiku）跑一個最小 prompt，貼出實際 stdout 報告、stderr 摘要行、`dispatch.jsonl` 實際內容——列為 `[憑據:step5]` 條目，在循環 step 5 收口。
