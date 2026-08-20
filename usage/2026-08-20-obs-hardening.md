# 使用情境報告 — 觀測性強化四項（failure 留痕、事件日誌、死檔清理、session hooks）  (run_id: 2026-08-20-obs-hardening)

- Spec：`spec/2026-08-20-obs-hardening.md`
- 風險報告（對照對策條目）：`risk/2026-08-20-obs-hardening.md`
- 分析日期：2026-08-20（前置 2，usage-analyzer）

> 本報告為觀測性/工具鏈基礎建設 Spec。此類功能無傳統「使用者送出表單」式 happy path；「使用」＝各 actor 在既有 Eval Flow 生命週期中觸發/消費這些機制。情境以「actor × 觸發時機」窮舉，邊界依 Step 3 清單逐條套用。

---

## 角色

- **主 flow agent**（人指揮的 AI）：跑 Eval Flow 的主體。放棄 run 時標 `aborted`＋填 `failed_reason`（項目 1a）；跑 `eval_state.py` 各子命令時觸發事件 append（項目 2a）；step 6 commit 時觸發防刪除 gate、既有 intent gate 與 aborted/failed 留痕窄例外 gate（項目 1b、1d）；session 啟動/resume/compact 後 session 重建時消費 SessionStart hook 的 stdout（項目 4）。
- **維護者**（人）：讀 `stats.py` 輸出（status 分佈含 `aborted`、事件數/時距/重入等新指標）與 `events.jsonl`／`gate_hits.log` 做修剪裁決；一次性手動清除目標端 `~/.claude/skills/_deprecated/`（項目 3c 收尾）；跑 `init.sh` 部署。
- **接手的 resume agent**（人指揮的 AI）：讀 `aborted`／`failed` manifest＋`failed_reason` 判斷「為何停、能否續」；讀 `events.jsonl` 還原「跑到哪、重試幾次」；讀 SessionStart hook 的殘留提示決定 resume 或標 aborted。
- **Claude Code runtime（系統/事件驅動 actor）**：session 開始/resume、以及 compaction 後 session 重建時觸發 SessionStart hook（matcher `startup|resume|compact`）；工具呼叫前觸發 PreToolUse gate。均非人手動呼叫，payload 由 runtime 餵入 stdin。（PreCompact hook 已於 Spec 修訂中取消——其 stdout 不進 context，見 Spec 項目 4 設計修訂節。）
- **commit gate（PreToolUse 內的自動 actor）**：`eval_gates.py` 於 `git commit` 前執行防刪除檢查（項目 1b）與 aborted/failed 留痕窄例外放行判定（項目 1d）。
- **`init.sh`（部署系統 actor）**：把 repo skills 同步到 `~/.claude/skills/`（排除 `_deprecated`）、合併兩個 hook 事件（PreToolUse＋SessionStart）到部署層 `settings.json`（項目 3c、4c）。

**被副作用影響、但不主動操作的 actor**：`doctor.py`／`test_docs_consistency.py`／`test_eval_gates.py` 的既有測試——文件↔實作漂移與 gate 迴歸會讓它們變紅（見互動點）。

---

## 情境

### 項目 1：失敗／放棄 run 的留痕（最小版）

#### A — 主 flow 放棄一個 run 並留痕（角色：主 flow agent）
- 前置：一個 `status: in_progress` 的 run，使用者或主 flow 決定不做了
- 操作：把 `run/<run_id>.json` 的 `status` 改為 `aborted`、填 `failed_reason`（一句話為何放棄）
- 預期：manifest 留在磁碟不被刪；`aborted` 語義（決定不做）與 `failed`（流程內判定失敗）明確區分
- I/O：input（manifest 手寫改欄位）/ output（`status: aborted` + `failed_reason` 非空的 manifest）/ 副作用：改寫 `run/<run_id>.json`；下游 `stats.py`、`check_other_runs`、`eval-flow-resume` 的行為改變（見互動點）
- 備註：`aborted` 加入的是 **manifest run-level status 枚舉**（文件在 `skills/eval-flow/SKILL.md:144`），**不是** `eval_state.py:33` 的 `STATUSES`（那是 sub_task 層 `passed/failed/in_progress`）。改錯枚舉是此 item 最可能的實作誤區。

#### A-err1 — 標 aborted 但漏填 failed_reason（角色：主 flow agent / commit gate）
- 觸發：`status` 設 `aborted`（或 `failed`）但 `failed_reason` 為 `null`／空，接著嘗試 commit 留痕
- 預期：由 Spec 1d 窄例外 gate **機械強制**——`failed_reason` 非空是窄例外放行的必要條件之一；空則不符窄例外、落回原 intent gate（status 非 completed → 擋）。不另立 prose 規則（HITL 裁決，開放問題 2）
- I/O：input（`status: aborted, failed_reason: null`）/ output（commit 被擋，訊息指示補 failed_reason）/ 副作用：無
- 備註：此機械強制點與 N（1d 窄例外）同一段程式碼；即「必填」的落實處

#### A-edge1 — failed 收尾與 aborted 的語義分野（角色：主 flow agent）
- 觸發：sub_task 修正 2 輪仍 🔴（既有 `skills/eval-flow/SKILL.md:226` 路徑）→ `status: failed`
- 預期：`failed`（流程內判定失敗）與 `aborted`（主動放棄）並存於枚舉；兩者 `failed_reason` 皆必填；兩者皆「永不清除」；兩者皆不得被視為 `in_progress`
- I/O：副作用：同 A（下游三消費點行為）

#### B — 防刪除 gate 攔截 commit 內的 manifest 刪除（角色：commit gate / 主 flow agent）
- 前置：某個 `run/<run_id>.json`（受 `MANIFEST_RE` 匹配）已被 git 追蹤；staged 變更含對它的刪除
- 操作：主 flow 執行 `git commit`（PreToolUse 觸發 `eval_gates.py`）
- 預期：`git diff --cached --diff-filter=D` 偵測到 manifest 刪除 → 擋 commit（exit 2），訊息指示「改標 aborted，不要刪」
- I/O：input（staged 含 `D` 狀態的 `run/*.json`）/ output（block，stderr 訊息）/ 副作用：寫 `run/gate_hits.log`（現由 `log_gate_hit` 記錄）
- 備註（風險報告業務#1）：`tests/test_eval_gates.py` 既有 711 行全綠為 baseline；新 gate 需正反向測試

#### B-edge1 — 刪除歸檔檔/baseline 檔應放行（角色：commit gate）
- 觸發：staged 含刪除 `run/<run_id>.eval.json` 或 `run/<run_id>.test_baseline.json`（`MANIFEST_RE` 的 `(?<!\.eval)(?<!\.test_baseline)` 負向斷言排除者）
- 預期：不受防刪除 gate 攔截，正常放行（Spec 1b 明列「歸檔檔/baseline 不在此列」）
- I/O：input（staged `D` 狀態的 `*.eval.json`/`*.test_baseline.json`）/ output（放行）/ 副作用：無

#### B-edge2 — Write/Edit 直接覆寫 manifest（已知限制，本版不攔）（角色：主 flow agent）
- 觸發：以 Write/Edit 工具把 manifest 內容清空/覆寫（非刪除、非 commit）
- 預期：**不攔**——Spec 項目 1 已知限制，hook matcher（`Bash|Task|Agent`，見 `.claude/settings.json:8`）不含 Write/Edit。此情境須在文件明載為覆蓋限制，避免誤以為已保護
- I/O：副作用：manifest 內容遺失（不受保護）

#### N — aborted／failed 留痕的窄例外 commit 放行（角色：主 flow agent / commit gate）
- 前置：一個中途放棄或失敗的 run，manifest 已標 `status: aborted`（或 `failed`）、`failed_reason` 非空
- 操作：`git add` **恰好只**該 run 的 manifest 一個檔（`run/<run_id>.json`，MANIFEST_RE 匹配），執行 `git commit`（附 `Run-Id:` trailer）
- 預期：Spec 1d 窄例外命中——staged 檔案集合恰等於該一個 manifest、且 `status ∈ {aborted, failed}`、且 `failed_reason` 非空 → **放行 commit**，並豁免 gate 1（`eval_state.json` 存在的攔截）。此為留痕進 git 的唯一 Claude 路徑
- I/O：input（staged 僅 `run/<run_id>.json`，status=aborted/failed、failed_reason 非空）/ output（commit 放行）/ 副作用：manifest 進 git（此後受防刪除 gate B 保護）；`eval_state.json` 若尚存在不擋（但仍須依收尾規則另行清理）
- 備註：失敗收尾的既有規則不變（staged 現場保留、使用者裁決）；本例外只服務「裁決後留痕」這一步

#### N-err1 — 窄例外條件不成立則不放行（角色：commit gate）
- 觸發：下列任一——staged 混入該 manifest 以外的其他檔（非「恰好一個」）／`status` 非 aborted 且非 failed／`failed_reason` 為空
- 預期：**不命中窄例外**，落回原 intent gate 判定（`eval_gates.py:131` status 非 completed → 擋；`:377` eval_state.json 存在 → 擋）。窄例外不得因夾帶其他檔而被繞用來 commit 未完成狀態
- I/O：input（staged 不符窄例外三條件之一）/ output（commit 被擋）/ 副作用：寫 `run/gate_hits.log`
- 備註：正反向測試（條件全滿足放行／混入其他檔不放行／status=completed 走原路）為 Spec 1d 的 DoD 硬性斷言

#### C — stats 計入並顯示 aborted 分佈（角色：維護者 / stats.py）
- 觸發：維護者跑 `python3 .claude/hooks/stats.py`，run 集合含 `aborted`
- 預期：status 分佈（`stats.py:63` 的 `Counter`、`:157` 輸出）計入 `aborted`。**證據：`Counter` 無寫死枚舉，`aborted` 自動計入**——Spec 1c「若寫死枚舉則放開」的前提在 `stats.py` 主計數點不成立，故此處預期為「確認即可、無需改碼」；**不專屬列出**（HITL 裁決，開放問題 6）；仍須斷言測試釘住
- I/O：input（含 aborted 的 `run/*.json`）/ output（`status：{..., 'aborted': N}`）/ 副作用：無（唯讀）

### 項目 2：run 事件日誌（append-only）

#### D — helper 子命令寫入狀態後 append 一行事件（角色：主 flow agent / eval_state.py）
- 前置：`eval_state.json` 存在且含 `run_id`
- 操作：跑任一寫入狀態子命令（`init`／`add-subtask`／`set-step`／`set-files`／`set-test`／`set-status`／`set-review`／`set-verify`／`add-verification`／`archive`）
- 預期：**主寫入成功之後**，append 一行 `{"ts": "<ISO8601>", "cmd": "<子命令>", "args": {…}}` 到 `run/<run_id>.events.jsonl`
- I/O：input（子命令＋參數）/ output（原命令輸出不變）/ 副作用：**append 到 `run/<run_id>.events.jsonl`**（新檔）；此檔 step 6 隨 manifest 同批 `git add`、永不清除
- 備註（風險報告技術#1）：append 必在主寫入成功後、整段 try/except、失敗僅印 warning 不改 exit code

#### D-err1 — events.jsonl 目錄不可寫（角色：eval_state.py）
- 觸發：`run/` 不可寫或 append 拋 OSError
- 預期：**主命令仍成功回傳**（記錄是旁路，不是 gate）；僅印 warning
- I/O：input（正常子命令）/ output（主命令成功、exit code 不變）/ 副作用：狀態寫入完成、事件未落地
- 備註：風險報告技術#1 對策；測試須斷言「events 檔不可寫時主命令仍成功」

#### D-err2 — eval_state.json 缺 run_id（角色：eval_state.py）
- 觸發：手動壞檔，`eval_state.json` 無 `run_id` → append 無目標檔名
- 預期：skip append＋warning（旁路原則，同 D-err1 處置）
- I/O：副作用：無事件落地、主命令不受影響
- 備註：風險報告資料#1 對策

#### D-edge1 — args 含長 blob，值須截斷（角色：eval_state.py）
- 觸發：`set-test --evidence` 等參數夾帶測試輸出/外部回應體/長 blob
- 預期：args **鍵全記、值截斷**（單值 ≤200 字元，超出加 `…[truncated]`）；不記錄環境變數類內容
- I/O：input（含長值參數的子命令）/ output（原命令輸出不變）/ 副作用：events.jsonl 該行的 args 值被截斷後寫入（進 git，寫入即永久）
- 備註：風險報告安全#1 對策（seed RETRO「外部回應體洩進 log」前科類別）

#### D-edge2 — 唯讀子命令不 append（角色：eval_state.py）
- 觸發：跑 `list-files`（唯讀，`eval_state.py:185`）
- 預期：**不 append 事件**（Spec 2a 明列排除；唯讀不算狀態變更）
- I/O：input（`list-files`）/ output（檔案清單）/ 副作用：無

#### E — stats 消費 events，輸出過程指標（角色：維護者 / stats.py）
- 觸發：維護者跑 `stats.py`，run 有 `events.jsonl`
- 預期：新增兩指標——①每 run 事件數與首尾事件時距（wall-clock 粗估）②`set-step` 重入次數（同一 sub_task 同一 step 出現 ≥2 次＝重試信號）
- I/O：input（`run/<run_id>.events.jsonl`）/ output（新指標行）/ 副作用：無（唯讀）
- 備註：時距與重入的計算是否依 `ts` 欄位、還是依檔內行序——見正確性假設 1

#### E-edge1 — 無 events 檔的舊 run（角色：stats.py）
- 觸發：舊 run（本 Spec 前建立）無 `events.jsonl`；或 Tier 1 run 無 `eval_state`（Spec 2b 已知覆蓋限制）
- 預期：顯示「無記錄」（不 crash、不猜）
- I/O：input（缺 events 檔的 run）/ output（該 run 指標＝「無記錄」）/ 副作用：無

#### F — gate_hits.log 納入版控（角色：維護者 / .gitignore）
- 觸發：修剪裁決需要 gate 命中證據跨 clone 持久
- 操作：`.gitignore` 移除 `run/gate_hits.log`（現於 `.gitignore:5`），該檔納入版控
- 預期：`gate_hits.log` 可 `git add`、commit、跨 clone 保留
- I/O：input（.gitignore 改動）/ output（檔納入版控）/ 副作用：此後每 run 的 commit 會顯示 `gate_hits.log` 變動（見開放問題 5）

### 項目 3：死觀測產物清理（僅刪除）

#### G — 刪除 scout/ 與 subagents_record/（角色：主 flow agent）
- 前置（已由本次盤點確認存在）：`scout/2026-07-25-tier2-p-worktree.md`、`subagents_record/2026-07-16.md`、`subagents_record/2026-07-17.md`
- 操作：刪除兩目錄
- 預期：機制已廢止（scout）／生產者退役（subagents_record，task-verifier 退役後）；manifest 的 `scout_report_path` 相容條文**不動**
- I/O：副作用：git 刪除兩目錄；須確認無現存程式碼/文件仍引用（見互動點）

#### H — 刪除 tests/check_worktree_isolation.sh（角色：主 flow agent）
- 前置：等價端到端覆蓋須存在——本次已確認 `tests/test_eval_gates.py:513` 有 `RunHookWorktreeRootTest`
- 操作：刪除 `tests/check_worktree_isolation.sh`
- 預期：刪除前以「`RunHookWorktreeRootTest` 存在」為 DoD 斷言（其 header 自述繞過 `run_hook()` 且曾產假綠燈，BUGLOG 2026-07-28）
- I/O：副作用：git 刪除該檔；須確認無 CI/其他 script 呼叫它（見互動點）

#### I — init.sh 與 doctor.py 排除 _deprecated（角色：init.sh / doctor.py）
- 觸發：部署（`init.sh` 第 5 步 skills 同步）與同步健檢（`doctor.py` 的 `check_skills_sync`／`list_skills`，`doctor.py:43`）
- 操作：`init.sh:86` 的 `for skill_path` 迴圈排除 `skills/_deprecated/`；`doctor.py:43` `list_skills` 排除 `_deprecated`
- 預期：已歸檔 skill 不部署到 `~/.claude/skills/`、不計入同步健檢；`init.sh` 維持「只覆蓋不刪除」語義（不負責刪除目標端既有殘留）
- I/O：input（repo `skills/*`）/ output（部署集合不含 `_deprecated`；健檢不計 `_deprecated`）/ 副作用：`init.sh` 與 `doctor.py` 兩端須同步排除，否則 `doctor` 會誤報「repo 有未部署」（`doctor.py:73` `repo_only` 邏輯）

#### I-edge1 — 目標端既有 _deprecated 一次性清除（角色：維護者）
- 觸發：`doctor.py` 排除 `_deprecated` 後，外層專案已部署的舊 `~/.claude/skills/_deprecated/` 變成無人監測殘留
- 預期：本 run 收尾時**手動**一次性清除，回報留痕（`ls` 前後證據）；`init.sh` 不負責刪除
- I/O：副作用：刪除目標端 `~/.claude/skills/_deprecated/`（本 run 一次性、手動、留痕）
- 備註：風險報告部署#2 對策

### 項目 4：SessionStart hook

> Spec 修訂（2026-08-20）：原 PreCompact hook **已取消**（其純文字 stdout 只進 debug log、不進 Claude context，無法達成提醒模型的目的）。改用 SessionStart 的 `compact` matcher——compaction 後 session 重建時觸發、stdout 注入 context。原 J（PreCompact）情境併入下方 K 的 `compact` matcher；載體修正、功能不變。

#### K — SessionStart hook 輸出殘留提示＋doctor 異常（角色：Claude Code runtime / 主 flow agent、resume agent）
- 觸發：runtime 觸發 `.claude/hooks/session_start.py`，matcher `startup|resume|compact`（三種進入點皆觸發：全新啟動、resume、以及 compaction 後 session 重建）
- 預期：stdout（純文字進 context）輸出兩部分——①偵測殘留 in_progress manifest（掃 `run/*.json`，`MANIFEST_RE` 同源判定）與殘留 `eval_state.json`，有則輸出「有未收尾的 run：<run_id>（phase=<phase>），依 eval-flow-resume skill 從檔案恢復，不靠記憶；或標 aborted 收尾」②`doctor.py --brief` 的異常行
- I/O：input（runtime SessionStart payload / 掃 `run/*.json`＋`eval_state.json` / `doctor.py --brief` 輸出）/ output（≤10 行 stdout 進 context）/ 副作用：跑 `doctor.py` 增 session 啟動延遲（風險效能#，`--brief` 走快路徑）
- 備註：`compact` matcher 承接原 PreCompact 的「compact 後靠檔案恢復、不靠記憶」目的；此處是「compact 後」而非「compact 前」提醒，符合 SessionStart 語義

#### K-edge1 — 無殘留且全綠時輸出空（角色：session_start hook）
- 觸發：無殘留 in_progress manifest、無殘留 `eval_state.json`、doctor `--brief` 全綠
- 預期：輸出空（不噪，不佔 context）
- I/O：output（空）/ 副作用：無

#### K-err1 — hook payload 解析失敗（角色：session_start hook）
- 觸發：stdin payload 格式非預期、解析拋錯
- 預期：**靜默 exit 0**（hook 壞掉不可拖垮 session）
- I/O：output（無）/ exit 0 / 副作用：無
- 備註：風險技術#2 對策；hook script 可用假 payload 直接 bash 執行測試

#### K-brief — doctor.py 新增 --brief 旗標（角色：doctor.py / session_start hook）
- 觸發：K 內嵌呼叫 `doctor.py --brief`
- 預期：僅輸出異常行；全綠時無輸出（供 4a 內嵌呼叫）；預設模式（無 --brief）行為不變
- I/O：input（`--brief`）/ output（僅異常行 / 全綠時空）/ 副作用：無

#### L — init.sh 合併兩個 hook 事件（冪等）（角色：init.sh / 維護者）
- 前置：部署層 `settings.json` 已存在（含既有 PreToolUse）
- 操作：`init.sh:58` 的合併 Python 由「只合併 PreToolUse」擴充為「同時合併 PreToolUse／SessionStart」
- 預期：兩事件皆合併、維持冪等（跑兩次結果相同）、不動其他鍵（`env`／`worktree`）；`.claude/settings.json` 註冊 SessionStart 事件
- I/O：input（repo `settings.json` 含兩事件）/ output（部署層 `settings.json` 含兩事件、其他鍵不變）/ 副作用：改寫部署層 `settings.json`
- 備註：合併需下一次 session 載入才生效（風險部署#1），本 session 無法端到端驗證 hook 真被觸發

#### L-err1 — 合併寫壞破壞既有 PreToolUse（回歸）（角色：init.sh）
- 觸發：擴充後的合併邏輯誤刪/覆寫既有 PreToolUse entry
- 預期：**不可發生**——合併後 PreToolUse 仍須指向 `gate-check.sh`，否則整條 gate 防線靜默消失（比新 hook 沒接上嚴重一個量級）
- I/O：副作用：若發生＝gate 防線失效
- 備註：風險技術#3 對策；DoD 綁定跑 `doctor.py`（既有檢查涵蓋 PreToolUse→gate-check.sh）＋合併函式冪等單元測試

#### M — hook 輸出上限約束（角色：session_start hook）
- 觸發：SessionStart hook 輸出
- 預期：stdout **≤10 行**（進 context 的成本要小；官方硬上限 10,000 字元）
- I/O：output（≤10 行）/ 副作用：無

---

## 與現有功能互動點

- **`eval_gates.py` commit gate（`:131`／`:377`；intent gate `skills/eval-flow/SKILL.md:234`）**：現行「manifest status 非 completed → 擋 commit」「eval_state.json 存在 → 擋 commit」。HITL 裁決（Spec 1d）加**窄例外**：staged 恰只該 manifest、status∈{aborted,failed}、failed_reason 非空 → 放行並豁免 eval_state 攔截（情境 N）；任一條件不成立落回原判定（N-err1）。新增防刪除 gate（B）與窄例外 gate（N）須與既有攔截共存、不得誤動既有判定（風險業務#1，baseline 711 行全綠）。
- **`check_other_runs`（`eval_gates.py:198`）**：只把 `status == "in_progress"` 視為佔用。`aborted`／`failed` 非 in_progress → **不擋新 run**（正確行為，須斷言釘住）。風險業務#2。
- **`eval-flow-resume`（`skills/eval-flow-resume/SKILL.md:12`／`:56`）**：掃 `in_progress` 恢復；`failed` 不自動恢復。`aborted` 亦不得被自動恢復（須與 failed 同待遇）。風險業務#2。
- **`stats.py`（status 分佈 `:63`／`:157`；gate_hits 消費 `:122`-`:181`）**：`Counter` 已自動計入 `aborted`（無寫死枚舉）；新增 events 指標（E）與 gate_hits 版控（F）為新消費。缺欄位顯示 n/a 不猜（既有原則 `:23`）。
- **`eval_state.py` 全體子命令（`:64`-`:214`）**：append 事件是**橫切**在每個寫入子命令上的副作用；必在主寫入後、包 try/except，否則弄壞所有 helper（風險技術#1）。這是回歸面最廣的一點。
- **`doctor.py`（`check_skills_sync`/`list_skills` `:30`-`:74`；殘留檢查 `:149`）**：`list_skills` 排除 `_deprecated` 須與 `init.sh` 同步，否則 `repo_only` 誤報（I）；新增 `--brief` 旗標（K-brief）；`doctor.py:149` 既有 eval_state.json 殘留檢查與 SessionStart 4a① 殘留偵測分工——SessionStart 掃 `run/*.json` 找殘留 in_progress manifest（doctor 不做），eval_state.json 殘留交 `doctor --brief` 報，避免雙報（開放問題 4 裁決＝照預設分工）。
- **`.claude/settings.json`（`:6` PreToolUse）**：新增 SessionStart hook 事件註冊＋`init.sh` 合併擴充為 PreToolUse＋SessionStart 兩事件；破壞既有 PreToolUse＝gate 防線失效（L-err1，風險技術#3）。（PreCompact 已取消，不註冊。）
- **`MANIFEST_RE`（`eval_gates.py:42`／`stats.py:33`，雙處同源）**：防刪除 gate（B）、窄例外 gate（N，判定「staged 恰只一個 manifest」）、SessionStart 掃描（K，找殘留 in_progress manifest）皆須**重用**此 pattern（`eval_gates.py:39`-`:41` 明訂單一判定點、禁 endswith/startswith 補丁）。
- **`tests/test_docs_consistency.py`**：step 6 ②清單、manifest 格式節、hook 清單多處文件須同步，否則此測試變紅（風險業務#3，DoD 硬性）。
- **`tests/test_eval_gates.py:513` `RunHookWorktreeRootTest`**：是刪除 `check_worktree_isolation.sh`（H）的等價覆蓋前提，刪前須確認其存在（本次已確認）。
- **`scout/`／`subagents_record/`／`check_worktree_isolation.sh` 引用面**：刪除前須 grep 確認無現存程式碼/CI/文件仍引用（G/H 的 DoD）。manifest `scout_report_path` 相容條文明確**不動**。

---

## 正確性假設清單（需使用者逐條裁示）

1. **events.jsonl 的行序＝時序（append-only 保序）** — 消費點：`stats.py` 新增的「首尾事件時距」與「`set-step` 重入次數」計算（E，本 run 新建，尚無 file:line）。被破壞時可觀察差異：**若消費端改依每行的 `ts` 欄位排序/取極值，則檔內行序被打亂也不改變輸出**（時距＝max(ts)−min(ts)、重入＝依 cmd+step 計數，均與行序無關）→ **疑似非需求，建議：消費端一律讀 `ts` 欄位、不依賴檔內物理行序**。裁示點：確認消費端以 `ts` 為準（則行序非需求，勿為它寫保序測試/探針），或明示要求物理行序（則須另立保序測試）。

2. **「append 在主寫入成功之後」的時序** — 消費點：`stats.py` 把 events 當「狀態真的變過」的證據（E）。被破壞時可觀察差異：若 append 在主寫入**之前**且主寫入隨後失敗，events.jsonl 會記下一筆從未生效的狀態變更 → 消費端算出的事件數/重試數虛高，且與 manifest 實際狀態不一致。**此為真需求**（有可觀察差異、有消費者），對策見風險技術#1，須測試釘住。

3. **`aborted` 的「非 in_progress」語義** — 消費點：`check_other_runs`（`eval_gates.py:198`）、`eval-flow-resume`（`skills/eval-flow-resume/SKILL.md:12`）。被破壞時可觀察差異：若任一消費點把 `aborted` 誤判為 in_progress → 擋住所有新 run、或觸發對已放棄 run 的自動 resume。**此為真需求**，須三消費點各加斷言（風險業務#2）。

4. **防刪除 gate 與窄例外 gate 的 manifest 身分判定＝`MANIFEST_RE`（含 `.eval`／`.test_baseline` 負向排除）** — 消費點：`eval_gates.py:42` `MANIFEST_RE`。被破壞時可觀察差異：若防刪除 gate（B）或窄例外 gate（N，判定「staged 恰只一個 manifest」）用 endswith/startswith 自行判定而非重用 `MANIFEST_RE`，會誤攔歸檔檔刪除（B-edge1 該放行卻被擋）、或把歸檔檔誤算進「恰只一個 manifest」而錯誤放行/擋 N。**此為真需求**（單一判定點硬約束，`eval_gates.py:39`-`:41`）。

---

## 開放問題（已於 HITL gate 裁決，逐條記錄結果供讀檔自足）

1. **`aborted`／`failed` manifest 如何進 git 被保護？（最關鍵）** — 現況：commit gate（`eval_gates.py:131`＋intent gate `skills/eval-flow/SKILL.md:234`）只放行 `status: completed`；且 `eval_state.json` 尚存在時擋 commit（`:377`）。防刪除 gate（項目 1b）只保護已被 git 追蹤的 manifest，中途放棄的 run 其 manifest 往往從未 commit（正常只在 step 6 完成時進 git）。
   - **裁決：採「窄例外 gate」**（已寫入 Spec 新增節 1d）——staged 檔案集合**恰好只含**該 run 的 manifest 一個檔（MANIFEST_RE 匹配）、`status` 為 `aborted` 或 `failed`、`failed_reason` 非空 → 放行 commit，並豁免 gate 1（`eval_state.json` 存在的攔截）。任一條件不成立 → 原判定不變。commit message 照附 `Run-Id:` trailer。失敗收尾既有規則不變（staged 現場保留、使用者裁決），窄例外只服務「裁決後留痕」這一步。對應情境：N（放行）／N-err1（不放行）。

2. **`aborted` 時 `failed_reason` 必填，用機械 gate 強制還是 prose 規則？**（Spec 1a）
   - **裁決：由 1d 窄例外 gate 機械強制**（`failed_reason` 非空是窄例外放行的必要條件之一）——**不另立 prose 規則**。對應情境：A-err1。

3. **hook script 用 `.sh` 還是 `.py`？**
   - **裁決：照預設**——Spec 4a 已定為 `.claude/hooks/session_start.py`（純 python，便於單元測試）。（PreCompact hook 已取消，不再有第二個 script。）對應情境：K。

4. **SessionStart 的殘留偵測與 `doctor.py` 既有 eval_state 檢查是否重複輸出？** — `doctor.py:149` 已報「eval_state.json 存在→有 in_progress run」；doctor 不掃 `run/*.json` 找 in_progress manifest。
   - **裁決：照預設分工**——SessionStart 掃 `run/*.json` 找殘留 in_progress manifest（doctor 不做的部分），`eval_state.json` 殘留交 `doctor --brief` 報，避免雙報。對應情境：K、K-brief。

5. **`gate_hits.log` 納入版控後的 commit 噪音**（Spec 2d）— 此檔每次 gate 命中都 append，納版控後每次收尾 commit 會夾帶其變動。
   - **裁決：照預設，接受**（修剪裁決需要跨 clone 的證據，是 Spec 明訂目的；噪音可容忍）。首次納版控前若對現存 `run/gate_hits.log` 歷史行有敏感內容疑慮，人工過目（首行已 `[:200]` 截斷，見 `eval_gates.py:71`）。對應情境：F。

6. **`aborted` 加入 `stats.py` 的顯示是否需要專屬呈現？**（Spec 1c）
   - **裁決：照預設，僅計入分佈數字**（`Counter` 已自動計入，不改碼、加斷言測試）；**不專屬列出**。已寫入 Spec 1c。對應情境：C。
