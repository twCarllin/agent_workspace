# 導航目標與共用工具鏈

## 授權及結果
使用者確認共同方案並要求完成兩階段、本地 commit、不 push。A 的路徑清單只用於導航；操作授權來自當次需求和適用指示。不得新增註冊表、可變 active_target 或解析 shell 字串推定目標。

## 已查證現況與診斷
- CLI 以 cwd 相對路徑保存狀態：`.agent-flow/scripts/eval_state.py:188-221`。2026-11-17 暫存 Git repo 的 pkg 內執行 init-run，exit=0，manifest 在 pkg/run，Git 根沒有 manifest。
- 寫入 gate 對 root 外路徑直接放行：`.agent-flow/scripts/eval_gates.py:416-420`。2026-11-17 非 Git A 以 --hook 重放 Write 到 B 的絕對路徑，B 有 init run，exit=0（應擋）。
- 派工 gate 在 hook cwd 檢查：`.agent-flow/scripts/eval_gates.py:612-614`；dispatch 自己沒有此檢查：`.agent-flow/scripts/dispatch.py:351-425`。
- Codex 角色從目標 cwd 讀取，Claude 使用 --agent：`.agent-flow/scripts/dispatch.py:192-218`。未完整安裝的目標缺角色。
- commit gate 只看 cwd/run：`.agent-flow/scripts/commit_message_gate.py:15-30`；安裝 hook 預設找主 checkout 的工具鏈：`install_harness.py:468-506`。
- preflight --harness codex：CLI 0.169.0、auth 通過；hook trust unknown；exit=2。設定存在不能作生效證據。

根因：CLI、寫入 hook、派工與 commit gate 使用不同的狀態根。
影響面：monorepo 子目錄、外部目標及未完整安裝目標的派工。
修法：共用可辨識契約的工作根判定，各 gate 使用自身實際目標。

## 設計及相容契約
1. 共用根判定服務區分 Git 根、狀態根和工具鏈來源。一般使用 Git 根；保留可辨識的既有子目錄安裝和合法舊 run。只存在 run 目錄不足以識別狀態根。檢查 manifest 的 run_id、tier、status、需求來源或 eval_state 引用及現有安裝標記。對多個有效狀態根的衝突列出位置並拒絕。commit 從 Git 根也必須發現合法子目錄狀態；不能只向上找。linked worktree 各用自己的狀態。
2. CLI 入口核對 cwd 和狀態根；錯目錄拒絕並指出根，不 chdir。非 Git 不開新完整 run。完整安裝目標使用自己的工具鏈；跨版本呼叫拒絕並指出適用腳本。
3. 輕量接入只寫 Git info/exclude 及受管 commit-msg hook，指向共用工具鏈。保留其他 hook 與 core.hooksPath；明確表示未啟用。重用現有標記並保留使用者內容。不得複製工具鏈。
4. Write/Edit/NotebookEdit/apply_patch 各實際路徑決定狀態根，包含新增、移除及搬移。重用開始前拒絕條件及例外。派工由 dispatch 自己檢查 cwd 目標；hook 不解析 cd/git -C。原生 Agent 無可確定跨專案目標時維持既有拒絕路徑，導航走 dispatch。
5. dispatch 在未完整安裝的 Git 目標注入同一來源角色、指示及 hooks。先查本地 CLI 的實際選項並實測；無法生效則明確阻擋及回報，不靜默降級。工作前明確讀目標與觸及模組指示；子程序也取得適用內容。保留權限政策。
6. 文件同步 skills 來源及入口。保留 adaptive Tier 1、舊 run、Tier 2；不搬移狀態、不改寫舊 manifest。

## 驗證及範圍
使用暫存 repo 執行真實 CLI 回歸：單 repo、monorepo、子目錄安裝／舊 run、A 到 B、非 Git A、linked worktree、根衝突、既有 hooks、合法／拒絕操作及派工。相關聯集及全套 python3 -m unittest discover -s tests。Claude/Codex 各實測從 A 寫 B 開始前阻擋、開始後放行、附加目錄、兩種 commit 寫法、子目錄 CLI、派工前 gate 和子程序指示／角色／hooks。客戶端、帳號、模型或 trust 缺少時記精確 blocked，交 coordinator 裁示，不記 pass。
非 Git 完整 flow、跨 repo 原子提交及完整依賴證據不在範圍。Bash 任意檔案寫入和 --no-verify 的原有限制須明列。

## 判級及待確認
Tier 2：跨子系統協調；預估主動工時 180 分鐘，含兩個 harness 真實驗證。無新增產品決策。必要 gate：確認以下兩 task／八 item 計畫。本 worker 執行限制為單一實作者，不派 helper；coordinator 已確認由其安排獨立審查，作者不可自行宣稱獨立通過。

## 計畫確認來源
實際使用者先前確認共同方案及「好，派一個 gpt-6.1-sol 的模型去完成吧」。coordinator 回覆 msg_d8a867b8fbac 核對兩 task／八 item 與上述已授權範圍相符，指示沿用既有授權繼續，未新增產品裁示；獨立 reviewer 由 coordinator 安排。此為授權來源核對，不記為使用者本輪另一次確認。

## 提交路徑裁決（Task 1 首輪紅色問題之修正）
coordinator 回覆 msg_3910df1cfaff 依既有架構授權作工程裁決，不是使用者另一次批准。移除用 A hook 推定 B 安全的提前放行。正式導航提交在 B cwd 執行 flow.py finish；既有 run_commit.py 增最小 commit 子命令，供 finish 共用，核對 B 的 cwd/run、staged 範圍、prepare 的 index tree 與 HEAD、原驗證/審查憑據及目標 hook，然後以 argv 呼叫 Git。原 prepare/finalize 入口及恢復契約保留。既有完整安裝者不增加操作；輕量目標先接入。自訂 hook/core.hooksPath 保留，已明確接入共用 gate 的自訂 hook 只由真正提交執行一次；沒有接妥則拒絕正式入口且不提交。
raw git 命令保留保守檢查，可能被 A 的未完成狀態先擋；不保證任意 raw 導航提交都能放行。缺可確定目標時，不能由 A 證明 B 的 hook 安全；也不宣稱所有未接入 B 的 raw 命令均可攔截。直接 cd/git -C 的命令若到達 B Git，B 已接入的 hook 仍拒絕不合規提交。既有 commit 的恢復只 finalize，不再提交。
驗收補充：A 未完成/B 未接入的 raw 回歸；正式入口 B 未接入或自訂未接妥時拒絕且無 HEAD 變化；A 未完成但已接入 B 的正式入口成功；prepare/驗證缺失及 stage 漂移拒絕；已有 commit 恢復不重複。

## Codex 正常信任接入（Task2 補充授權）
使用者明示「ok, 幫我測試。 然後這個問題也要處理」，coordinator msg_48c8c0b72a57 將已發現的正常信任接入問題納入同一需求，不重問是否開始。
dispatch 在啟動 child 前讀原生 inventory，精確 runtime hooks 未 enabled/trusted 時拒絕且不啟動 child。拒絕輸出實際 provider 的 command/hash、保留既有權限的互動 Codex 命令及逐項 /hooks 審閱方法；不自動批准、不寫 trusted_hash、不 trust-all、不 bypass。正常核准後可直接重試同一任務與 run；定義改變後須重新審閱，不能把來源 A 的信任無條件移給其他來源。正式工具鏈路徑穩定，同一來源在 B/C 產生相同定義並重用正常信任；隨機 provider 僅用於隔離測試。
驗收包含未批准拒絕且 run 不變、正常批准後重試、modified/disabled 拒絕；至少一組原生能力實證，其他精確回歸可用既有外部 client seam。正常測試 setup/teardown 的授權依 msg_d6bd1bf80ed4，只透過原生 config/batchWrite 對兩精確候選定義操作，最新 user-layer expectedVersion 防止覆寫，保留所有其他設定；完成後精確移除本次原先不存在的兩筆信任。真實客戶端的 sandbox 或命令權限拒絕分開記錄，不算目標 Git hook 已驗證。
