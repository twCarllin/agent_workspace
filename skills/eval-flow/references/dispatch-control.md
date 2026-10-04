# 派工與證據控制

## 派工機制（headless CLI；本節為單一枚舉點）

流程角色（`code-writer`／`task-verifier`／`code-reviewer`／`retro`／`task-decomposer`／`usage-analyzer`／`impact-analyzer`）可由目前 harness 的角色工具或 headless CLI 派工。兩路都遵守共用角色契約、獨立審查與 gate；工具與權限差異住 `.agent-flow/HARNESS.md` 及適配層：

- **指令**：`python3 .agent-flow/scripts/dispatch.py <role> --prompt-file <path> [--backend claude|codex] [--resume <session>] [--files <逗號清單>] [--timeout <秒>] [--max-output-chars <n>]`。後端依 manifest `harness` 選取；明示 `--backend` 可覆寫，舊 manifest 缺 harness 時使用 Claude 相容路徑。角色職責讀共用 `.agent-flow/roles/`，模型與工具設定由各 harness 載體提供
- **prompt 檔**：主 flow 把派工 prompt 全文（含硬性約束區、契約表原文——知識前置規則不變，R-011）寫到 `run/<run_id>.prompt-<role>-<n>.md`（冷溯源檔，不進版控）再派工，不走命令列參數
- **輸出**：stdout＝子 agent 報告全文（主 flow 直接讀）；stderr 摘要行 `[dispatch] role=… backend=… session=<sid> turns=… tokens=… cost_usd=…`；exit 2＝信封 blocking（退件重取，見「主 flow 憑據紀律」）、exit 3＝子程序失敗／超時（預設 1200 秒）／報告超量（預設 60000 字元，截斷）、exit 4＝越界變更（退件；範圍外檔案列在 stderr，優先於 exit 2）
- **越界檢查（主 flow 派 code-writer 時必帶 `--files`，值＝該 item 的 files 欄）**：script 以派工前後的 `git status` 對照，「派工後新出現且不在清單內」的路徑即越界。越界退件時主 flow 先看 stderr 清單裁決（真越界→`--resume` 要求還原；清單漏列→補 files 後照常收），不自行放行
- **修正輪**：同一角色的修正／重取以 `--resume <sid>` 沿用原 session（context 仍熱，省重建稅），`<sid>` 取自上一輪 stderr 摘要行
- **信封驗收內建**：script 以 `report_envelope_check.check_envelope` 判定（單一出處），blocking／advisory 處置同 PostToolUse hook（該 hook 仍掛在 `Agent` 工具路徑上）
- **權限**：CLI 相容模式與原生工具的執行前提見目前 harness 適配層；目前 session 必須已授權該模式。CLI 派工為前景子程序
- **留痕**：每次派工 append `run/<run_id>.dispatch.jsonl`（格式見 `SKILL.md「資料格式與操作規則」`），`token_usage.py` 收尾時併入用量；gate 7 對命令工具派工指令同樣生效（見 `SKILL.md「Gate 的硬性執行」`）
- **範圍外**：parallel-run／[P] fan-out 使用獨立 Git worktree 與各 harness 的隔離執行方式；不能用背景旗標代替隔離

## Model 指派原則

- agent→model 的可執行設定來源住 `.agent-flow/harnesses/models.json`；指派理由住 repo 根 `MODEL_POLICY.md`：Claude 端由 `.claude/agents/*.md` frontmatter 承載；Codex 端由 `.codex/agents/*.toml`（共用安裝器 `install_harness.py` 產生）承載，`tests/test_model_policy.py` 強制兩端與政策表一致。不同平台各自驗證，不共用模型 ID
- 指派準則：**推理／判斷密集的規劃與審查（拆解、情境盤點、審查）→ 強 model；機械式、量大的執行 → 快 model**。規劃階段一次判斷錯，整條 flow 重跑的成本遠高於強 model 的單價
- 例外：前置 1 分拆 task 在主 flow 直建門檻內（≤2 tasks 且 ≤8 items）時由主 flow 直接執行，無 frontmatter 可指定，沿用主 session model

## Subagent 呼叫原則（省 token）

- **code-reviewer**（升級輪呼叫）需要讀取程式碼變更時，**必須在 prompt 中指示使用 `git diff --cached -- <files>`**（命令工具，`<files>`＝當前 sub_task 的 `files` 欄），不要逐檔讀取完整檔案。
  - `git diff` 只回傳變更部分，token 消耗遠低於讀整檔；file-scoped 指令另可避免跨 sub_task staging 累積污染（見循環 step 2）
  - **task-verifier（checker，預設輪呼叫）不讀 diff、不適用本條**——輸入集見循環 step 3，只附 `--stat` 輸出
- **auto-mode 定義**：指使用者在本次 session 中**明確表示**開啟（例如「開 auto-mode」「全自動跑」）。未明示一律視為關閉，不可自行推斷。
- **背景執行與權限**：依 `.agent-flow/HARNESS.md` 與目前 harness 適配層執行。主 flow 等待交付與必要的 HITL gate 後才可續跑；流程不授予額外權限。
- **usage-analyzer / task-decomposer**：可依 harness 能力背景產出。usage 答案併入 Spec；task-decomposer 自檢完成後才進計畫確認 gate。Tier 1 仍由主 flow 做輕量計畫確認。

## 主 flow 憑據紀律（回報必附證據）

Flow 對 subagent 有滿滿的防線（引文核實、仲裁稽核、hook gate），但主 flow 自己是無防線單點（R-013——長 run 發生過主 flow 假報進度）。因此：

- **主 flow 的每一句進度宣稱（「已派審」「已修復」「測試通過」「報告已產出」）必須同句附上可驗證憑據**：agent launched 回執、測試輸出尾行、`git diff --cached --stat`、`ls` 檔案存在證明。**沒有憑據的進度句，讀者（含接手者與使用者）應當作未發生。**
- 這是 `local_test_evidence` 精神的推廣：證據要求不只在測試欄位，而在主 flow 所有進度回報。
- **subagent 報告信封缺損 → 二分處置（原則：表現層問題只警告、不觸發付費重試）**：
  - **blocking**（缺終行 `Self-check:`，或 task-verifier 缺兩節關鍵詞）＝疑似截斷或未完成交付，主 flow 不得逕行解析該報告內容，須退件重取（重新呼叫該 subagent）——**重取最多 1 次**；第 2 次仍缺 → 不再重取，主 flow 人工檢視該報告內容（判斷是否完整可用）並在回報留痕一句「信封第 2 次缺損，人工檢視採用／退件」
  - **advisory**（只缺首行戳記行）＝表現層缺項，**不退件**：hook 以 PostToolUse `additionalContext` 回傳警告，主 flow 照常解析報告、在回報留痕一句
  - 由 PostToolUse hook（`.agent-flow/scripts/report_envelope_check.py`）機械偵測——blocking 時 exit 2 的 stderr 即標準化退件訊息；hook 屬品質 lint、fail-open（解析異常放行），人工檢查為兜底、不因 hook 存在而豁免（兩類項目與載荷的單一枚舉點住 `SKILL.md「Gate 的硬性執行」` 信封 lint 節）
- 與 write-ahead 的關係：`eval_state` 的 `step` 欄記的是**意圖**（打算做），憑據才是**動作發生的證明**——兩者缺一不可，resume 時以憑據對賬（見 eval-flow-resume skill）。

## 資料格式與操作規則

- **一律用 helper script 更新，不手動 Edit**：`python3 .agent-flow/scripts/eval_state.py`——子命令清單、理由與各時機的操作規則住 `SKILL.md「資料格式與操作規則」` 操作規則節（單一枚舉點，R-007），不在此重列
- **首輪審查結果出來後（step 3）**：執行 `set-review <id> <🔴數> [--dimensions '<json>']`——**checker 輪固定填 0**；升級輪有 🔴／🟡 時 `--dimensions` 必填；commit gate 必填 `<🔴數>`，缺一擋歸檔。參數完整語義與維度詞彙表住 `SKILL.md「資料格式與操作規則」` 操作規則節
- Run manifest／`eval_state.json`／`events.jsonl` 完整格式、欄位語義與其餘操作規則見 `.agents/skills/eval-flow/SKILL.md「資料格式與操作規則」`——init 填欄、step 3 記審查結果、resume 對賬、欄位語義查詢時讀取
