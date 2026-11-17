<!-- agent-workspace managed -->
# Codex adapter

共用執行契約見 .agent-flow/HARNESS.md。Codex 安裝入口同時寫在專案 AGENTS.md 的管理區段與 `.codex/config.toml` 頂層 `developer_instructions`。安裝器保留 AGENTS.md 的其他文字；專案設定只有在受信任專案才載入，因此不能以設定檔存在推定入口生效。本 repo 自身以 AGENTS.md 為入口。專案層 developer_instructions 會蓋過使用者層同名鍵，安裝時若專案層尚無此鍵，先複製使用者層原文再附加區段；之後修改使用者層，需重跑安裝器同步。專案 skills 為 .agents/skills/，角色設定為 .codex/agents/*.toml，hooks 為 .codex/hooks.json。

角色所需的讀取、搜尋、寫入、命令能力使用目前 Codex session 工具。角色工具可用時使用相符的角色名稱；CLI 派工用 dispatch.py --backend codex。模型與推理設定由 harnesses/models.json 的 Codex 設定產生。

原生 `spawn_agent` 一律明確指定 `fork_turns: "none"`，不繼承完整主對話。派工資料與修正輪沿用方式依 `.agents/skills/eval-flow/references/dispatch-control.md`「派工上下文」及「修正輪」；上下文選擇不改角色模型或權限。

子 agent 沿用父 session 權限。背景與 worktree 依目前工具能力執行。Claude 的 Bash 批准、run_in_background 與 Agent isolation 欄位不適用。CLI 派工省略 `--permissions` 時，有寫入工具的角色用 `edits`（`--sandbox workspace-write`），其他角色用 `inherit`（不附權限覆寫，遵守子 CLI 自身設定，不能保證繼承未保存的父程序權限）。明確指定 `--permissions unrestricted` 才使用完整權限旗標。

Codex 回報不使用 Claude PostToolUse payload；主 flow 或 dispatch.py 檢查必要節與 Self-check 終行。用量由 `token_usage.py <run_id> --write` 讀取本機 Codex session 紀錄與派工留痕。主 session 或時窗無法確認時標示部分／未知，不把缺值填零；本機紀錄不代表實際帳單金額。

新 run 記 harness: codex 與 evidence_schema: 2；以共用 run_verify.py、run_commit.py 完成驗證與提交。hooks 安裝後仍須依客戶端要求檢查與信任。既有 commit-msg hook 與 core.hooksPath 保留，依安裝輸出接入共用提交 gate。SessionStart 透過 AGENT_FLOW_HARNESS=codex 明示 harness。

共用 harness_adapter.py 轉換 CLI 結果與工具事件。PreToolUse 接 Bash／Agent／apply_patch；patch 的新增、修改、刪除及搬移目標逐一經過寫入 gate。真實工具支援與 hook trust 必須以執行證據確認。

輕量目標在其 cwd 使用來源 dispatch.py。來源讀取目標自訂 agent 設定，缺少時讀來源編譯設定或共用角色；將角色文字及目標／模組指示放入子程序 prompt，模型與推理仍使用角色設定。這是 CLI prompt 適配，不宣稱原生 Agent 已載入不存在的目標角色檔。runtime hooks 以該次 `-c hooks.<event>` 傳入，指向同一來源的絕對路徑，不在目標複製工具鏈。

共享 Codex 派工先用同一 CLI 的唯讀 `app-server hooks/list` 檢查 sessionFlags hooks 已啟用且受信任；無法確認時拒絕啟動子 agent，指出 `/hooks` 正常審閱入口。請用相同精確定義開啟互動 Codex，逐項審閱來源、命令與 hash 後依既有批准操作信任；修改定義後須重新審閱。dispatch 不寫 trusted_hash、不自動批准、不略過 hook trust，sandbox 與權限不因導航改變。正常信任及實際工具事件均需驗證；單次診斷繞過信任的結果不能當正式接入成功。

未信任的拒絕輸出包含本次實際 command/hash 與可直接執行的互動命令。進入 `/hooks` 後逐項選取列出的 SessionFlags handler，核對精確定義再由使用者批准，不使用 trust-all。完成後直接重試同一派工，不重新初始化 run；modified 或 disabled 仍拒絕。不同目標使用同一穩定來源路徑時，runtime 定義相同，可沿用正常信任；不為每個目標建立隨機 provider。信任設定存在仍須由原生 inventory 確認，客戶端 sandbox 拒絕 `.git` 寫入時不能宣稱正式提交成功或 Git hook 已執行。

`edits` 維持 workspace-write；Codex 可將 `.git` 留為受保護區，正式提交可能需要客戶端正常的單次命令批准。互動 session 或原生 approval broker 須把精確 command/cwd 交給使用者審閱，不自動接受其他命令、不改成 unrestricted、不加入 `.git` writableRoot。無正常批准通道的 headless 執行應明確回報受限；不能承諾 workspace-write 自動可提交，也不以 hook trust 取代命令批准。
