# Spec — 跨 Harness 執行與驗證

## 目標與授權

使用者確認「好，照你計畫的執行吧」：修評測、補 Adapter 與權限設定、驗證兩種 CLI 的完整流程、改善安裝預覽與失敗還原。共用任務與驗收可選 Codex 或 Claude Code；執行工具仍是必要依賴。不宣稱對話或模型內部狀態可直接轉移。

目前工作樹內，上一輪已授權的模型設定與 HTML 說明納入本次成果；TODO.md、run/gate_hits.log、run/tier0.jsonl 為既有紀錄，保留但不提交。這份計畫的四項範圍已由使用者確認，不重複請求批准。

## 情境與完成條件

- A：同一個評測案例可選 claude 或 codex；fixture 由共用安裝器建立，技能連結可解析。
- B：派工預設不加完整權限旗標；只有明確選擇 unrestricted 才加。CLI 預設遵守自身設定，不虛稱能自動繼承父程序未保存的權限。
- C：兩種工具的命令、角色、檔案修改事件轉成共用格式後執行既有 gate；Codex apply_patch 的每個目標（含 Move to）皆需檢查。
- D：安裝 dry-run 不修改目標；使用者改過的受管理檔案可辨識，預設停止且列出衝突；安裝中途失敗，還原本次寫入、刪除與 symlink，包括 Git hook。
- E：真實 CLI 驗證正常完成、違規阻擋、測試失敗處理、中斷恢復；保存版本、退出碼、證據與能力限制。模型、登入、trust 不可用時記 blocked，不當 pass，也不偷偷改模型。
- F：本地確定性整合測試驗證同一組流程契約；真實模型執行是另列的證據，不放入預設單元測試。

## 作廢舊行為與相容

| 舊行為 | 新行為 |
|---|---|
| skill_eval 僅 claude，fixture 手動複製 .claude 且漏 .agents | --harness claude/codex，安裝器建立專案入口、skills、角色與 hooks |
| dispatch 固定全放行 | --permissions inherit（預設，不附權限覆寫）或 unrestricted（明確 opt-in），模式記入派工紀錄 |
| Codex PreToolUse 只 Bash/Agent | 包含 apply_patch；原有 Claude 事件仍支援 |
| 安裝逐檔直接寫、marker 視同可覆寫 | 預覽＋內容雜湊 ownership＋暫存規劃＋可回復 apply；衝突不覆寫 |
| 有輸出就執行 checker，錯誤或成本未知可能被當正常 | adapter 回傳共同結果，工具錯誤與不可解析不算 pass；Codex 成本未知記 null，不偽造 dollar cap |

保留 init.sh、install_codex.py 與 .claude/hooks 相容入口，既有角色、模型、信封規則、git hook 自訂設定。舊 manifest 缺 harness 沿用 claude；既有評測旗標與 exit 0/1/2 語義保留。既有測試斷言只能依上表更新，禁止删掉存活行為覆蓋。

## Adapter 介面（先建立，其他工作再依賴）

新增 .agent-flow/scripts/harness_adapter.py，純標準庫；共用執行器消費該模組。

- build_argv(harness, *, role=None, model=None, reasoning_effort='low', resume=None, permissions='inherit', budget_usd=None) → CLI argv，prompt 走 stdin '-'; Codex 有 model 才附 -m；角色模型由來源設定決定。
- parse_result(harness, stdout, returncode=0) → dict：result(str/null), session_id(str/null), model(str/null), num_turns(int/null), total_cost_usd(number/null), usage(dict), is_error(bool), error(str/null), budget_exhausted(bool)。保留可供既有 checker 使用的 result 鍵。
- normalize_hook(payload) → 共用 dict（cwd、tool_name、tool_input），保留 Claude/Codex Bash，轉 exec_command.cmd；apply_patch 提取所有檔案目標給既有 write gate。非法輸入不可拋未捕捉例外。
- capabilities(harness) → 明確支援項（美元預算、權限、hooks 等）；Codex 不支援 CLI dollar budget，不偽造成本。

偽代碼：build argv（validate harness/permissions → shared args → harness args）; parse result（decode JSON/JSONL → collect session/message/usage/error → normalize）; hook（validate object → resolve canonical tool → extract safe inputs/patch paths → existing gates）。

## 安裝演算法

plan(target, harness): 在暫存區建立候選檔 → 讀取 ownership manifest → 比較「上次雜湊／目前內容／新內容」→ 列 create/update/delete/preserve/conflict。
apply(plan): 衝突先停止 → 保存會改動的檔案、symlink、mode → 同目錄 tempfile＋replace 每個檔案 → 最後更新 ownership manifest → 若失敗逆序還原，清除本次新建空目錄。

ownership 只管理本安裝器產出的檔案；入口 managed section、混合 hooks/config 必須保留使用者區段，不能以整檔雜湊禁止合法自訂。未知 legacy 自訂檔預設保留。不得追隨目標 symlink 寫入專案以外位置。dry-run 不建立目標或改 Git 設定。rollback 指程序捕捉到的失敗，不能宣稱斷電或強制 kill 也原子。

## 真實驗證與限制

新增可重跑的 CLI smoke runner，在暫存 Git 專案執行；默认預覽，明確執行旗標才呼叫模型。Codex 模型維持 gpt-6.1-sol；Claude 沿用專案政策。限制時間與執行次数。hook trust 必須可驗證；禁止藉停用 hook 湊 pass。

結果至少區分 deterministic / live，與 pass / fail / blocked；保存 CLI 版本、選用模型、實際權限模式、各案例證據。四個 live 情境共用相同契約，模型錯誤或 hook 未啟用不能算流程 pass。

新增測試涵蓋安裝後執行實際子程序、預覽不寫、改動衝突、rollback、symlink 與空白路徑；事件的異常輸入、Codex file gate、兩種 JSON 格式、失敗與 timeout。針對完整權限預設、patch gate、rollback 各做一次 mutation self-check（移除防線時測試須失敗）。

## 範圍外

不新增第三種工具、不變更流程 HITL 政策、不做遠端部署、不改機器全域模型設定、不保證產出逐字相同。HTML 與文件更新到實測進度，不能把待驗列為完成。

## 本次收尾範圍（2026-10-04）

使用者要求先完成 Codex。只執行 Codex 的真實 CLI 驗證；Claude Code 測試延期，保留相容實作但不宣稱已驗證。本地共用回歸不呼叫 Claude CLI。
