<!-- agent-workspace managed -->
# Flow 本地操作

在專案根目錄執行 `python3 .agent-flow/scripts/flow.py`。這個入口使用現有 manifest、事件與驗證腳本；agent 仍負責需求判斷、實作及適用的自查或獨立審查。

## 查看啟動狀態

```sh
python3 .agent-flow/scripts/flow.py activation --json
python3 .agent-flow/scripts/flow.py activation --run-id <id> --json
```

結果分列入口設定、已記錄的 Router 判級、run 狀態與 hook 設定。入口是否被客戶端讀取、hook 是否在目前 session 執行，沒有原生事件證據時一律顯示 `unknown`；不能以設定檔存在推定生效。要驗證原生 hook，可在隔離 fixture 執行 `harness_smoke.py --live --harness codex --case normal --permissions edits --trust-local-hooks`；其結果只證明該次隔離執行，不證明目前 session 的信任狀態。

## 開始前檢查

```sh
python3 .agent-flow/scripts/flow.py preflight --harness codex --run-id <id> --json
python3 .agent-flow/scripts/flow.py preflight --harness codex --run-id <id> --live --timeout 30
```

首次尚未建立 manifest 時省略 `--run-id`；manifest 已存在時再指定。

靜態檢查涵蓋安裝檔案、模型設定、CLI、登入、工作目錄寫入和測試命令。測試命令只檢查入口，正式驗證由 `finish` 執行。模型來源是 `harnesses/models.json`，Codex 使用 `gpt-6.1-terra`。

`--live` 才啟動有時間上限的 Codex 模型探針。探針會使用模型用量，只驗證模型與登入；無工具呼叫的成功結果不能證明 hooks 已信任或已執行。設定存在與原生執行證據分開回報，未確認項目記為 `unknown`。

Claude 執行 `claude --version` 與 `claude auth status`，只記錄版本與登入是否通過，不輸出帳號資料；`--live` 同樣啟動 Claude 模型探針（每次預算上限 0.10 美元）。Claude 原生 CLI smoke 已於 2026-10-05 以 Claude Code 2.1.285 通過四個案例。退出碼：0 為 ready；1 為 blocked；2 為 unknown 或操作錯誤。靜態檢查有 unknown 時仍可讀取具體檢查結果。

`inputs-v2` 快照檢查內嵌 repository。一般未追蹤的內嵌 repository 只有在 Git 已批准的忽略範圍內才跳過；工具不自行修改 exclude。尚未排除時提前回報具體路徑，排除政策變動會使舊證據失效。已追蹤 gitlink／submodule 目前明確拒絕，須先解決工作目錄支援限制，不能以只記 HEAD 當作已驗證。既有 inputs-v1 與 legacy 紀錄沿用原格式。

## 查看進度

```sh
python3 .agent-flow/scripts/flow.py status --run-id <id>
python3 .agent-flow/scripts/flow.py status --run-id <id> --json
python3 .agent-flow/scripts/flow.py watch --run-id <id> --timeout 30 --interval 1
```

輸出包括紀錄狀態、task 步驟、耗時、失敗原因與下一個動作。省略 run ID 時只能自動選取唯一未完成的 run；有多個 run 時必須指定。紀錄的步驟表示執行意圖，不能當成 agent 仍在執行的證明。

派工後優先使用完成通知或工具提供的阻塞等待；等待時長遵守目前 session 工具與回報限制。只有需要介入、補資料、有停滯證據或使用者要求時才主動查進度，不為例行回報反覆呼叫 `status`、讀取相同日誌或短間隔輪詢。工具沒有完成通知時使用其等待介面；等待逾時後按工具契約繼續等待，不把逾時當成停滯。必要回報沿用最後已觀測證據並標示沒有新結果。

主 flow 回報狀態時，分開說明程序是否存活、最後已觀測進展與受阻原因，只使用目前可取得的證據。沒有新輸出不足以判定卡死，程序存活也不足以證明工作有進展；原因無證據時記未知。timeout 只表示相應操作的等待上限已到，是否終止須另有證據。例如「最後收到工具開始事件，已等待 40 秒；未收到完成事件，等待原因未知」。本規則不表示 `status/watch` 已具備程序探測能力，也不要求新增心跳、輪詢或必填欄位；既有停止條件照常適用。

`watch` 只在狀態改變時輸出，達到時間上限或 run 結束時退出。可用 Ctrl+C 停止監看。監看不會暫停工作，也不修改證據。

## Tier 1 初始化與審查

新 `init-run` 記 `tier1_policy: "adaptive-v1"`。適用判斷與問題觸發條件見
`skills/eval-flow/references/tier1.md`；Tier 2 沿用逐 task 的獨立審查。

```sh
python3 .agent-flow/scripts/eval_state.py init-run --run-id <id> \
  --harness codex --spec-inline '<需求>' --tier-rationale '<理由>' \
  --test-command 'python3 -m unittest discover -s tests' --task-file task/<計畫>.md
python3 .agent-flow/scripts/eval_state.py start-run <id> --authorization '<使用者已授權的需求>'
# 實作、stage並選擇需求所需的驗證範圍
python3 .agent-flow/scripts/run_verify.py --run-id <id> --cmd '<實際驗證命令>'
python3 .agent-flow/scripts/eval_state.py review-run <id> 0 \
  --checked-by self --evidence '<逐項完成度、驗證範圍與剩餘限制>' --passed
```

`start-run` 凍結 item 清單並推進 decomposed；記已授權需求而不填 HITL 確認。
有待使用者決定的問題時先提問，用 `hitl-confirm <id> --note '<實際裁示範圍>'`
記錄真實確認。headless 不能自行確認 HITL；沒有問題的已授權新 Tier 1 可直接開始。

有獨立審查原因時，先執行 `require-review <id> --reason '<具名原因>'`；原因只增不減，
清除舊通過，直接派 code-reviewer。拿到實際結果後以 `review-run --checked-by reviewer:manual`
記錄；自查不能代替必要的獨立審查。`review-run` 不執行測試；`self` 要求目前來源的成功
驗證及非空完成度證據，來源變更或測試失敗後須重新驗證與核對。

`start-run` 記 `started` 事件，`require-review` 記 `review_required`；兩者都只記已發生的操作。
`plan_timestamp()` 對 adaptive 優先使用 `plan_recorded_at`，否則採真實 HITL 時間。
`self_review_snapshot` 保存驗證來源快照、快照格式及計畫時間；提交時仍核對目前狀態。

缺 `tier1_policy` 的舊 run 保留 `hitl-confirm` 與獨立 checker／reviewer 路徑，不能用
`start-run` 或 `self`。`init-run` 拒絕覆寫 manifest；紅數非零不可宣告通過。事件只記已發生
的操作，缺資料不推定成功。未結清 item、未授權移除或部分交付仍由既有 gate 阻擋。

## worktree 連結

```sh
python3 .agent-flow/scripts/flow.py worktree-link
python3 .agent-flow/scripts/flow.py worktree-link --root <worktree 路徑>
```

工具鏈檔案不進專案 commit，所以新 worktree 一開始沒有 `.agent-flow/`、`.agents/`、`.claude/`、`retro/` 與 `CLAUDE.local.md`。PreToolUse 與 SessionStart hook 解析出 worktree 根之後，會自動補建相對 symlink 指回主工作區；缺哪個補哪個，已存在的路徑不動。`run/` 與 `task/` 是每個 run 的狀態，各 worktree 獨立，不建連結。

手動 `git worktree add` 建立的 worktree，或要在 worktree 內起新 session 恢復 run 之前，先在該 worktree 執行本指令。全部連結已存在時印「無需建立連結」；在主工作區執行不建任何連結。

## 獨立檢核資料

Tier 2 與有具名審查原因的新 Tier 1 直接派 reviewer 審完整 task diff、需求與證據。舊 Tier 1 派 checker 前依 [REVIEW_PACKET.md](REVIEW_PACKET.md) 組裝資料包，標準派工使用 `dispatch.py task-verifier --review-packet <檔案>`。必要資料缺漏時先補齊，ready 只表示資料與來源有效，不代表審查通過；checker 保留四類升級判斷。

## 收尾

先只 stage 本次檔案，完成適用的自查或獨立審查並記錄憑據，再收尾。

```sh
git add -- src/example.py tests/test_example.py
python3 .agent-flow/scripts/flow.py finish --run-id <id> \
  --message 'Implement example' --files src/example.py tests/test_example.py \
  --verify-command 'python3 -m unittest discover -s tests'
```

`finish` 依序核對範圍與既有憑據、執行 `run_verify.py`、歸檔符合條件的 Tier 2 狀態、執行 `run_commit.py prepare`、Git commit 與 finalize。它不推定審查通過，也不自動 stage 檔案；測試欄位由實際驗證結果產生。驗證命令依 test-strategy「依變更選擇驗證」；純設定使用必要設定／操作檢查，程式部分保留適用回歸範圍，專案另有要求時依專案規則。

已知命令只依本地輸入決定結果時，可加 `--reuse` 沿用同 run、同指令、同輸入與環境的成功證據；外部服務或實際環境檢查應實跑。`finish` 對 schema 2 的本地命令只顯示驗證摘要，完整輸出保存在 `run/<id>.verify-<序號>.log`；失敗時另顯示輸出末 40 行。若舊成功紀錄沒有完整輸出檔，首次使用精簡輸出時須提供 `--rerun-reason evidence_refresh` 才會實跑。直接使用 `run_verify.py` 的預設輸出行為不變，可另加 `--quiet-success` 取得相同的精簡輸出。

有額外 staged 檔、範圍內未 stage 修改、其他 run 的熱狀態、未完成審查或驗證失敗時停止。錯誤保留原始輸出，已有現場與證據保留。提交訊息自動加入唯一的 `Run-Id` trailer。

遠端／實際環境證據不得僅以本地快照相同而沿用，依 test-strategy 的目標狀態核對規則。明確加上 `--reuse` 才嘗試沿用本 run 中命令、輸入與環境相同的本地成功驗證；不符合時，輸入變更或前次失敗可直接重跑；其餘情況須提供重跑原因。若 commit 已成功而 finalize 中斷，重跑同一指令會核對提交後補 finalize，避免重複 commit。

明確加上 `--push` 才推送至目前分支的 `origin` 遠端；不使用 force。完成後 push 失敗，可重跑帶 `--push` 的指令。同一 Git repository（含 worktree）同時只允許一個 finish；程序中斷留下的鎖須先核對程序已停止再處理。

本版提供 `activation/preflight/status/watch/review-packet/worktree-link/finish`；初始化與審查記錄使用上述 `eval_state.py` 入口。需求分級沿用 Router，工作暫停與恢復沿用 eval-flow-resume。

## 已追蹤的活動日誌

框架來源與測試 fixture 進版控；執行產物的保留規則見 Eval Flow「測試、收尾與回顧」。Git 忽略規則不影響已追蹤檔案。舊專案若仍追蹤下列活動日誌，在確認遷移範圍後執行：

```sh
git rm --cached -- run/gate_hits.log run/tier0.jsonl
```

此操作只取消追蹤，保留本地內容；提交前核對檔案仍存在，且 `git check-ignore` 確認忽略規則生效。本模板已有 `run/` 忽略規則，安裝到目標專案時由安裝器設定。其他已追蹤的歷史 manifest 與報告保留，不能整批刪除 `run/`。新 checkout 的執行日誌由工具按需建立。

## Item 交付對帳

2026.10.19.1 起的新 Tier 1／2 run 必須記 `item_accounting_required: true`。
開始時固定 `item_plan.confirmed_at` 與 `items`（`id`、`task_id`、`summary`）。
adaptive Tier 1 由 `start-run` 依已授權需求建立，或有決策時用真實 `hitl-confirm`；舊 Tier 1 保留 HITL。計畫時間由共用 `plan_timestamp()` 定位；Tier 2 在 HITL 後執行：

```sh
python3 .agent-flow/scripts/item_accounting.py --run-id <id> confirm-plan
python3 .agent-flow/scripts/item_accounting.py --run-id <id> deliver 1.1 --files src/file.py
python3 .agent-flow/scripts/item_accounting.py --run-id <id> pending 1.2 --reason '待使用者裁示'
python3 .agent-flow/scripts/item_accounting.py --run-id <id> remove 1.2 --ruling-file ruling.json
python3 .agent-flow/scripts/item_accounting.py --run-id <id> partial --items 1.2 --ruling-file ruling.json
```

裁示 JSON 須有 `actor: "user"`、原文 `text`、含時區的 ISO 時間 `at`、來源 `source`。
`pending` 使 run 暫停；只有使用者裁示可移除 item 或接受部分交付。
`partial_acceptance.item_ids` 須列出全部未交付 item，`ruling` 保存裁示。
`partial` 是終態，不表示全部完成。不得刪除 task item 來消除未完成範圍。

`run_commit.py prepare` 與 commit gate 先核對 staged 檔案；`finalize` 再核對
真實 commit 的父 SHA、Run-Id 與檔案。交付檔案缺失時，補齊本次提交內容再重試。
新 run 缺計畫時，先依已確認的 task 建立計畫。舊版 manifest 沿用原契約，
不補造確認時間或交付結果。

部分交付仍須通過 task 審查與四項測試／審查憑據。reviewer 須明列未交付 item
及使用者裁示，才可對已接受的部分範圍記 task `passed`；未獲裁示仍阻擋。

## 用量紀錄

- `subagent_usage`：**選填**。step 6 子項②收尾時由 `python3 .agent-flow/scripts/token_usage.py <run_id> --write` **實測回寫**的 tokens 彙總 `{"prep": int, "loop": int, "main": int}`——三鍵皆為 transcript 四欄（`input_tokens`／`cache_creation_input_tokens`／`cache_read_input_tokens`／`output_tokens`）加總；`prep`＝usage-analyzer／task-decomposer／impact-analyzer 的 subagent 合計、`loop`＝其餘 subagent 合計、`main`＝主 flow 自身。不以 Agent 工具回執自報、不憑印象估 `main`（估計法系統性低估流程稅）。消費端 `stats.py`：prep／loop 缺一或非 int → 整筆計無記錄；`main` 非 int → 只跳過 main、prep/loop 照收

- `token_usage`：**選填**。與 `subagent_usage` 同時由 `token_usage.py --write` 寫入的明細：`{"session_id", "window": [lo, hi]|null, "main": {四欄＋turns}, "subagents": [{"agent_type", "description", 四欄＋turns}]}`；`window` 取自 `events.jsonl` 首尾 `ts`（init 之前的判級／載 skill 用量不在窗內，屬已知低估面）；`subagents` 為 transcript `subagents/` 目錄 ∪ `run/<run_id>.dispatch.jsonl` 派工留痕（後者 `description` 為 `dispatch:<backend>`、不切窗）。純記錄，無 gate 消費

相同成功指令且輸入未變時，優先用 `--reuse` 沿用證據。必須重跑時，`run_verify.py` 與 `flow.py finish` 均須提供 `--rerun-reason user_requested|environment_changed|evidence_refresh`；原因須符合實際情況。未填且無法重用時，在子程序啟動前阻擋。輸入變更與前次失敗由工具自動分類。
