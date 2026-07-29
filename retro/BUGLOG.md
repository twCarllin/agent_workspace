# BUGLOG（bugfix 根因證據層）

每筆 bugfix 修完由主 flow append 一行；同模組或同根因分類第 2 次命中時提煉約束句升級進 RETRO.md（規則見 CLAUDE.md「工作型態前判」）。

格式：`- YYYY-MM-DD［模組路徑］根因分類：根因一句`（已升級者尾註 `↑RETRO`）

---
- 2026-07-22［.claude/hooks/test_baseline.py｜skills/test-strategy］架構限制：baseline 快照歸因有盲區（related 全 repo 掃超出 test_command 範圍、環境／日期漂移、參數化 ID 變動），既有失敗被 check 判為新失敗，模型自查歸因空轉燒 token 且結論不持久化、每個 sub_task 回鍋重查
- 2026-07-28［.claude/hooks/eval_gates.py｜tests/check_worktree_isolation.sh］驗證盲點：`run_hook()` 以 `CLAUDE_PROJECT_DIR` 決定 gate 套用的工作區，但該變數釘死在 session 啟動目錄、不隨 git worktree 移動，導致 worktree 內的 run 誤用主工作區狀態（subagent gate 誤判、commit gate 讀空 index 而靜默失效）；既有的 `check_worktree_isolation.sh` 直接呼叫 `check_other_runs()` 繞過 `run_hook()` 的 root 解析，名為驗證 worktree 隔離卻對此 bug 零訊號、還給出 4/4 綠燈
- 2026-07-29［.claude/agents/*.md｜skills/（report-format、review-checklist、eval-scoring 等 6 個）］複製貼上：checklist 與報告模板的內容被複製進 agent 定義後於該處持續演進，原始 skill 檔留在 `~/.claude/skills/` 成為無人維護的舊版副本——未納版控、無投放路徑（subagent 無 `Skill` 工具、frontmatter 未宣告），而主 flow 的 prompt 仍以名字引用它們，形成「宣稱依據 A、實際執行 B」；其中 report-format 的 reviewer 模板缺現行硬性的「完成度節」，eval-scoring 依賴已移除的 eval-scorer agent。本 run 僅完成納入版控（使汰除可逆），投放路徑與汰除處置待續
