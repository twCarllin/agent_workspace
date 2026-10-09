<!-- agent-workspace managed -->
# Codex adapter

共用執行契約見 .agent-flow/HARNESS.md。Codex 入口為 `.codex/config.toml` 頂層 `developer_instructions` 的 Eval Flow 區段（安裝器寫入、受信任專案才載入，不改寫專案 AGENTS.md；本 repo 自身為 AGENTS.md）。專案層此鍵會蓋過使用者層同名鍵，安裝時若專案層尚無此鍵，先複製使用者層原文再附加區段；之後修改使用者層，需重跑安裝器同步。專案 skills 為 .agents/skills/，角色設定為 .codex/agents/*.toml，hooks 為 .codex/hooks.json。

角色所需的讀取、搜尋、寫入、命令能力使用目前 Codex session 工具。角色工具可用時使用相符的角色名稱；CLI 派工用 dispatch.py --backend codex。模型與推理設定由 harnesses/models.json 的 Codex 設定產生。

子 agent 沿用父 session 權限。背景與 worktree 依目前工具能力執行。Claude 的 Bash 批准、run_in_background 與 Agent isolation 欄位不適用。CLI 派工省略 `--permissions` 時，有寫入工具的角色用 `edits`（`--sandbox workspace-write`），其他角色用 `inherit`（不附權限覆寫，遵守子 CLI 自身設定，不能保證繼承未保存的父程序權限）。明確指定 `--permissions unrestricted` 才使用完整權限旗標。

Codex 回報不使用 Claude PostToolUse payload；主 flow 或 dispatch.py 檢查必要節與 Self-check 終行。主 session 用量無資料時記 unknown_codex，不改為零。

新 run 記 harness: codex 與 evidence_schema: 2；以共用 run_verify.py、run_commit.py 完成驗證與提交。hooks 安裝後仍須依客戶端要求檢查與信任。既有 commit-msg hook 與 core.hooksPath 保留，依安裝輸出接入共用提交 gate。SessionStart 透過 AGENT_FLOW_HARNESS=codex 明示 harness。

共用 harness_adapter.py 轉換 CLI 結果與工具事件。PreToolUse 接 Bash／Agent／apply_patch；patch 的新增、修改、刪除及搬移目標逐一經過寫入 gate。真實工具支援與 hook trust 必須以執行證據確認。
