# Spec：觀測性強化四項（failure 留痕、事件日誌、死檔清理、session hooks）

- run_id：`2026-08-20-obs-hardening`
- 日期：2026-08-20
- 來源：與 apache/maka 架構比對後的改進裁決（僅承接其架構不變量：append-only 證據、status 須有證據支撐、compaction 不得使狀態蒸發；不移植其實作）
- 背景數據（`python3 .claude/hooks/stats.py`，2026-08-20 實測）：30 run 全部 `completed`、零 `failed`／`aborted`；`hitl_rejections` 0/30 從未寫入；`verification_commands` 僅 6/30 有記錄；gate 命中 13 次全屬 gate 1；`run/gate_hits.log` 被 gitignore

## 使用者裁決（2026-08-20，Spec 定稿前確認）

1. **修剪範圍**：只清死檔，**不刪任何 gate**。零命中 gate 的裁決延後——等本 Spec 的觀測機制落地、累積約 5 個 run 的有效數據後，再依 TODO.md §15 正式裁決。
2. **失敗記錄深度**：採**最小版**（aborted 留痕＋防刪除 gate），不做事件日誌推導版（Terminal Invariant 推導 status 的方案不在本次範圍）。

## 目標

系統目前只記錄成功（30/30 completed），失敗語料庫是空的；遙測欄位靠 agent 自律填寫而系統性缺漏。本 Spec 把「失敗留痕」與「過程記錄」從模型自律改為程式碼路徑，並清除已死的觀測產物。**淨新增 prose 規則數目標 ≤2 條**；其餘全部走機械路徑（helper 程式碼、hook 設定、刪除）。

## 範圍（四項）

### 項目 1：失敗／放棄 run 的留痕（最小版）

現況：`status: failed` 與 `failed_reason` 欄位存在但 30 個 run 從未使用；被放棄的 run 沒有留下任何痕跡（manifest 疑似被刪或覆蓋）。

1a. **`aborted` 語義入格式**：`skills/eval-flow/SKILL.md` 的 manifest 格式節，`status` 枚舉加 `aborted`——語義＝使用者或主 flow 決定不做了（與 `failed`＝流程內判定失敗區分）。標 `aborted` 時 `failed_reason` 必填（一句話：為何放棄）。manifest「永不清除」規則明文涵蓋 aborted／failed run。
1b. **防刪除 gate（機械）**：`.claude/hooks/eval_gates.py` commit gate 新增檢查——staged 變更中出現 `run/*.json`（依 `MANIFEST_RE` 匹配者）的**刪除**（`git diff --cached --diff-filter=D`）→ 擋 commit，訊息指示改標 `aborted`。歸檔檔／baseline 檔不在此列（不受 MANIFEST_RE 匹配）。
1c. **stats 消費端**：`stats.py` 的 status 分佈已存在，確認 `aborted` 會被計入並顯示（若寫死枚舉則放開）；不專屬列出（HITL 裁決，開放問題 6）。
1d. **aborted／failed 留痕的窄例外 gate**（HITL 裁決新增，開放問題 1＋2）：現行 intent gate 只放行 `status: completed`，中途放棄的 run 留痕無法由 Claude commit。`eval_gates.py` 加一條窄例外：staged 檔案集合**恰好等於**該 run 的 manifest 一個檔（`git diff --cached --name-only` 機械判定，MANIFEST_RE 匹配）、且其 `status` 為 `aborted` 或 `failed`、且 `failed_reason` 非空 → 放行 commit，並豁免 gate 1（`eval_state.json` 存在擋）。任一條件不成立 → 原判定不變。此例外同時是 `failed_reason` 必填的機械強制點（不另立 prose 規則）。commit message 照附 `Run-Id:` trailer。失敗收尾的既有規則不變（staged 現場保留、使用者裁決）；本例外只服務「裁決後留痕」這一步。

已知限制（記入風險報告即可，不修）：Write／Edit 工具直接覆寫 manifest 內容的路徑不在 hook matcher 內，本版不攔——僅攔刪除與 commit 面。

### 項目 2：run 事件日誌（append-only，含消費端同批落地）

現況：`eval_state.json` 是可變單例，每次寫入覆蓋前值；step 6 只歸檔最終狀態。過程資訊（何時進哪一步、重試幾次、耗時多久）全部蒸發。`hitl_rejections`／`verification_commands` 靠自律記錄而系統性缺漏。

2a. **寫入端（程式碼路徑，零新規則）**：`.claude/hooks/eval_state.py` 每個**會寫入狀態的子命令**（init／add-subtask／set-step／set-files／set-test／set-status／set-review／set-verify／add-verification／archive；唯讀的 list-files 不記）在成功寫入後 append 一行 JSON 到 `run/<run_id>.events.jsonl`：`{"ts": "<ISO8601>", "cmd": "<子命令>", "args": {…}}`。run_id 取自 eval_state.json。append 失敗**不得阻斷**原子命令（記錄是旁路，不是 gate）。
2b. **歸屬與生命週期**：`run/<run_id>.events.jsonl` 是**冷溯源檔**，step 6 收尾隨 manifest 同批 `git add`、永不清除（eval-flow skill step 6 子項②清單補一項；Tier 1 不建 eval_state 故無此檔，屬已知覆蓋限制、記入格式節一句）。
2c. **消費端（同批落地，防 scout/ 式死亡）**：`stats.py` 新增兩個指標——每 run 事件數與首尾事件時距（wall-clock 粗估）、`set-step` 重入次數（同一 sub_task 同一 step 出現 ≥2 次＝重試信號）。無 events 檔的舊 run 顯示「無記錄」。
2d. **遙測持久化**：`.gitignore` 移除 `run/gate_hits.log`，該檔納入版控（修剪裁決的證據基礎必須跨 clone 持久）。

### 項目 3：死觀測產物清理（僅刪除，不刪 gate）

3a. 刪除 `scout/`（機制已廢止，manifest 的 `scout_report_path` 相容條文不動）與 `subagents_record/`（task-verifier 退役後無生產者）。
3b. 刪除 `tests/check_worktree_isolation.sh`——其 header 自述繞過 `run_hook()` 且曾產出假綠燈（BUGLOG 2026-07-28）；等價的端到端覆蓋已由 `tests/test_eval_gates.py` 的 `RunHookWorktreeRootTest` 提供（刪除前須確認此覆蓋存在，作為 DoD 斷言）。
3c. `init.sh` 第 5 步 skills 同步排除 `skills/_deprecated/`（已歸檔的 skill 不應部署到 `~/.claude/skills/`）；`doctor.py` 的 `list_skills` 同步排除 `_deprecated`（不再計入同步健檢）。目標端既有的 `~/.claude/skills/_deprecated/` 由本 run 一次性手動清除，init.sh 不負責刪除（維持「只覆蓋不刪除」既有語義）。

### 項目 4：SessionStart hook（把「靠記得」變機械事實）

現況：`.claude/settings.json` 只註冊 PreToolUse。compaction 後「重新載入 eval-flow skill」靠 agent 記得；`doctor.py` 從不自動執行。

> 設計修訂（2026-08-20，依官方 hooks 文件查證）：原構想的 PreCompact hook 已**取消**——PreCompact 的純文字 stdout 只進 debug log、不進 Claude context，無法達成「提醒模型」的目的（其唯一能力是 exit 2 阻擋 compaction，非本 Spec 所需）。改用 SessionStart 的 `compact` matcher：compaction 後 session 重建時觸發，stdout 純文字會注入 context。功能不變、載體修正。

4a. **SessionStart hook script**：新增 `.claude/hooks/session_start.py`，註冊 matcher `startup|resume|compact`。輸出到 stdout（純文字進 context）：①偵測殘留 in_progress manifest（掃 `run/*.json`，MANIFEST_RE 同源判定）與殘留 `eval_state.json`，有則輸出「有未收尾的 run：<run_id>（phase=<phase>），依 eval-flow-resume skill 從檔案恢復，不靠記憶；或標 aborted 收尾」②`doctor.py --brief` 的異常行（見 4b）。無殘留且健檢全綠時輸出空（不噪）。stdin payload 解析失敗一律靜默 exit 0（hook 壞掉不可拖垮 session）。
4b. **doctor.py 加 `--brief` 旗標**：僅輸出異常行，全綠時無輸出（供 4a 內嵌呼叫；預設模式行為不變）。
4c. **部署接線**：`.claude/settings.json` 註冊 SessionStart 事件；`init.sh` 的 settings 合併邏輯擴充為同時合併 PreToolUse／SessionStart（維持冪等、不動其他鍵）。
4d. **hook 輸出上限**：stdout ≤10 行（進 context 的成本要小；官方硬上限 10,000 字元）。

## 明確不做（本 run 範圍外）

- 不刪任何 gate、不降級任何 HITL（等有效數據）
- 不做 status 推導版（Terminal Invariant）——events.jsonl 落地後若要升級，另開 run
- 不做 benchmark task set 與 CI（使用者裁決：項目 5 忽略）
- 不動 `.claude/settings.local.json` 的權限白名單（已向使用者揭露，屬使用者自裁範圍）
- 不攔 Write／Edit 工具的 manifest 覆寫（見項目 1 已知限制）

## 驗收總則

- 全套測試：`python3 -m unittest discover -s tests` 無新增穩定失敗
- 新行為（1b gate、2a append、2c stats 指標、4a/4b hook script、3c init.sh 排除）各有自動化測試（Tier 2 硬性）
- `VERSION` 升版；本 Spec 的變更行為在 doctor.py／文件一致性測試下不產生漂移（`tests/test_docs_consistency.py` 通過即證）
