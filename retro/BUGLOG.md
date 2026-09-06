# BUGLOG（bugfix 根因證據層）

每筆 bugfix 修完由主 flow append 一行；同模組或同根因分類第 2 次命中時提煉約束句升級進 RETRO.md（規則見 CLAUDE.md「工作型態前判」）。

格式：`- YYYY-MM-DD［模組路徑］根因分類：根因一句`（已升級者尾註 `↑RETRO`）

**選填尾註 `[checker-passed]`（回退機制 v3，2026-09-05 起）**：eval-flow 循環 step 3 由 `task-verifier`（checker）checker-only 放行的 item，事後爆 bug 且根因屬「reviewer 讀 diff 可攔」型時，本行加註 `[checker-passed]`（機械留痕，不影響既有格式）。append 時 grep 同根因分類＋`[checker-passed]` 尾註，**第 2 次命中 → 強制停下、產出裁決 packet 交使用者**：packet 含兩個 bug 的根因、checker 當輪審查落檔、四個選項附成本——(a) 上游規則提案（retro 產出＋出生證）(b) 新增升級觸發⑥（該類特徵命中即派 reviewer）(c) 恢復 reviewer 預設 (d) 接受風險。**agent 不可自行選任一補救**（比照 Hotfix「不可自行認定」原則），不設自動總開關，每次命中都過人。

---
- 2026-07-22［.claude/hooks/test_baseline.py｜skills/test-strategy］架構限制：baseline 快照歸因有盲區（related 全 repo 掃超出 test_command 範圍、環境／日期漂移、參數化 ID 變動），既有失敗被 check 判為新失敗，模型自查歸因空轉燒 token 且結論不持久化、每個 sub_task 回鍋重查 ↑RETRO
- 2026-07-28［.claude/hooks/eval_gates.py｜tests/check_worktree_isolation.sh］驗證盲點：`run_hook()` 以 `CLAUDE_PROJECT_DIR` 決定 gate 套用的工作區，但該變數釘死在 session 啟動目錄、不隨 git worktree 移動，導致 worktree 內的 run 誤用主工作區狀態（subagent gate 誤判、commit gate 讀空 index 而靜默失效）；既有的 `check_worktree_isolation.sh` 直接呼叫 `check_other_runs()` 繞過 `run_hook()` 的 root 解析，名為驗證 worktree 隔離卻對此 bug 零訊號、還給出 4/4 綠燈 ↑RETRO
- 2026-07-29［.claude/agents/*.md｜skills/（report-format、review-checklist、eval-scoring 等 6 個）］複製貼上：checklist 與報告模板的內容被複製進 agent 定義後於該處持續演進，原始 skill 檔留在 `~/.claude/skills/` 成為無人維護的舊版副本——未納版控、無投放路徑（subagent 無 `Skill` 工具、frontmatter 未宣告），而主 flow 的 prompt 仍以名字引用它們，形成「宣稱依據 A、實際執行 B」；其中 report-format 的 reviewer 模板缺現行硬性的「完成度節」，eval-scoring 依賴已移除的 eval-scorer agent。本 run 僅完成納入版控（使汰除可逆），投放路徑與汰除處置待續 ↑RETRO
- 2026-07-29［skills/parallel-run｜skills/eval-flow（fan-out 節）］驗證盲點：skill 步驟 5–6 規定「主 session 建 worktree → spawn 背景 agent，工作目錄固定在自己的 worktree」，但 harness 不提供這條路——從 repo root 啟動的 subagent cwd 被釘死，`EnterWorktree` 明文拒絕從 repo root 做 path 切換，兩支背景 agent 皆於第一步即無法起跑；該啟動契約自 2026-07-15 寫成後從未被執行過一次，Tier 2 [P] fan-out 節重用同一契約故一併失效 ↑RETRO
- 2026-07-30［skills/eval-flow/SKILL.md（step 6 子項②／Tier 1 精簡路徑／[P] fan-out 節）｜skills/test-strategy］複製貼上：「收尾要 git add 哪些檔」的枚舉清單被複製到三處各自維護，step 6 的清單漏列 `run/<run_id>.test_baseline.json`（與 test-strategy「此檔隨 commit 進 git」不一致），Tier 1 與 fan-out 兩處又各有自己的版本——實際造成兩個 run 的 baseline 靜默遺失（2026-07-25-tier2-p-worktree、2026-07-30-reviewer-citation-discipline，後者於清理 worktree 前搶救才未遺失）；且修正時只改到 step 6、Tier 1 與 fan-out 兩處同義敘述當場漏改，由 reviewer 抓出 ↑RETRO
- 2026-08-04［init.sh（step 3 hooks 部署）］疏忽：.gitignore 補 __pycache__（03a8d79）時未同步稽核同目錄的另一個消費端——init.sh 對 hooks 用裸 `cp "$SRC"/*`，撞上生成目錄即報錯、`set -e` 使腳本在 step 3 中斷，chmod／settings 合併／skills／RETRO seed 全部靜默缺失（部分部署無任何錯誤留痕）；實際造成報價系統一次部署失敗，任何跑過測試的 clone 皆會踩。修法：改 `find -maxdepth 1 -type f` 只複製一般檔案
- 2026-09-06［.claude/agents/task-verifier／死引用］B5 全檔重寫 task-verifier 為 checker 時沿用舊輸出節的「工作紀錄寫 subagents_record/」指示——該目錄 2026-08-20 已隨死觀測產物清除（當時 task-verifier 已退役故其引用留置未清），重寫復活了死指示，checker 首戰執行時重建死目錄；舊制 reviewer 當輪（2026-09-05-checker-default st2 r1/r2）聚焦升級碼分歧未掃到輸出節殘留
- 2026-09-06［.claude/hooks/test_baseline.py｜skills/test-strategy］架構限制：cmd_baseline 單次執行即把暫時性套件層非零退出（`__suite__`）永久記入 stable_failures，check 的差集扣除使 gate 對後續全套崩潰靜默失明且跨 run 沿用傳染——與 check 端既有的惰性重跑確認不對稱（同模組第 2 次命中 07-22 條 → 升級 R-010）↑RETRO
