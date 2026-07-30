# Task — 孤兒 skill 汰除歸檔  (created: 2026-07-30)

> run_id: `2026-07-30-deprecate-orphan-skills`（Tier 1 精簡路徑，**序列執行**）。需求原文見 manifest 的 `spec_inline`。
> 現行全套測試基線：`python3 -m unittest discover -s tests` → **162 tests, OK**。
> **為何序列而非並行**：本需求原列入 2026-07-30 並行批次，執行中發現必須修改既有測試（見下），違反並行模式「既有測試只增不改」的硬前提——該規則是 merge gate 全套綠燈的裁判前提，破掉它綠燈就不構成安全證據。依 `parallel-run` 卡住協定退出並行，經使用者裁示改由主 session 序列執行（序列模式允許「有意行為變更同步既有測試」，須寫依據）。

## 背景（自足，不依賴對話）

2026-07-29 將 6 個原本只存在於 `~/.claude/skills/`、未納版控的 skill 複製進 repo（commit `1e8dae7`），目的是讓後續汰除成為可逆操作。其中 5 個經逐一比對確認為死檔或陳舊副本：

| skill | 判定依據（已查證） |
|---|---|
| `eval-scoring` | 其消費者 `eval-scorer` subagent 已移除（`.claude/agents/eval-scorer.md` 不存在，於 run `2026-07-17-remove-eval-scorer` 刪除），為死檔 |
| `report-format` | 其「A. 程式碼審查報告」模板**缺「完成度節」**，而 `.claude/agents/code-reviewer.md` 現行明訂該節為硬性（「缺此節報告無效」）；「D. 任務完成度驗證報告」描述已退役的 task-verifier 職責 |
| `review-checklist` | 5 大範疇已內嵌於 `code-reviewer.md`，且 skill 版缺現行的「維度標記」機制 |
| `task-verify-checklist` | 內容已內嵌於 `.claude/agents/task-verifier.md` |
| `task-checklist` | 全 repo 零引用；`task-decomposer` 掛的是 `task-decomposition` 而非它，無消費者 |

`root-cause-table` 被 `CLAUDE.md` 實際引用（BUGLOG 根因分類用），是**活檔，留在原處**。其餘 7 個原有 skill 亦不動。

**汰除方向的依據**：subagent 沒有 `Skill` 工具、agent 定義亦未以 frontmatter 宣告依賴，「skill 當 single source、agent 引用它」在本 harness 下不成立（2026-07-29 以 code-reviewer 實測確認：它的 checklist 與報告模板來自自身 system prompt，不是 skill）。故陳舊副本應退場，不是重新接線。

## 兩個必須一起處理的耦合點

1. **`doctor.py` 的部署同步健檢**：`.claude/hooks/doctor.py` 的 `check_skills_sync` 比對 repo `skills/` 與 `~/.claude/skills/`。`list_skills()` 只列頂層目錄（`_deprecated` 會被當成「一個 skill」）、`dirs_equal()` 遞迴逐位元比對。**只動 repo 側會立刻紅燈**（5 個 repo-only 漂移），故兩側須對稱移動。已於 `/tmp` 複本模擬驗證：雙邊對稱移動後 `check_skills_sync` 回報「同步一致（9 個 skill）」，**無須修改 `doctor.py`**。
2. **`tests/test_agent_refs.py` 的例外清單**：其 `SCAN_FILES` 用 `(ROOT/"skills").glob("*/SKILL.md")`——**僅一層**。移動後 `skills/_deprecated/eval-scoring/SKILL.md` 落到第二層而脫離掃描，而它是全 repo **唯一**引用 `eval-scorer` 的來源。於是例外清單的 hygiene 檢查（「清單中的 agent 若文件中已無引用，應從清單移除」）如設計般觸發紅燈。
   **修法依據（測試過時，非放寬）**：該測試檔第 31 行註解已明文預告「待 eval-scoring skill 汰除後，從例外清單與掃描來源同步移除本條目」——本 run 正是它預期的時點。移除例外**嚴格非放寬**：豁免路徑是 `if name in EXCEPTION_LIST: continue`，清空 dict 只會減少 continue、讓更多斷言實際執行，不存在「原本會抓到的錯誤現在被放過」的路徑。精確地說是**條件性收緊**——穩態下 `eval-scorer` 隨 `eval-scoring` 一併離開單層 glob（被掃的 ref 集合實際變小），收緊只在該檔重回掃描範圍時兌現（即 DoD 8 驗的場景）。兩條依賴 EXCEPTION_LIST 的 hygiene 測試對空 dict 迭代零次、空轉通過，但會在任何新例外加入時自動復活；真正防止主檢查零命中假通過的是 `test_non_vacuous`（釘住 `code-writer`／`task-decomposer` 必被掃到），它不依賴該清單、原封不動仍全程有效。

## 明確不做的事（scope 邊界）

- **不刪除任何 skill 檔案**（只移動，保留可回溯）
- **不修改任何 skill 的內容**（移動後須逐位元相同，`git diff -M` 應顯示為 rename）
- 不修改 `.claude/hooks/doctor.py`（已驗證無須改）
- 不修改任何 agent 定義、`CLAUDE.md`、其他既有 skill
- 不修改 `tests/test_agent_refs.py` 除例外清單那一條之外的任何部分（判準、掃描邏輯、其他測試案例皆不動）
- 不新增測試

## Task 1: 汰除歸檔與測試同步

- [x] 1.1 5 個 skill 兩側對稱移入 `_deprecated/` ＋ 移除 `test_agent_refs.py` 的 `eval-scorer` 例外條目  ~10 行（移動為 rename，實質新增行數極少）  files: `skills/eval-scoring/SKILL.md`, `skills/report-format/SKILL.md`, `skills/review-checklist/SKILL.md`, `skills/task-checklist/SKILL.md`, `skills/task-verify-checklist/SKILL.md`（皆移入 `skills/_deprecated/`）, `tests/test_agent_refs.py`
      DoD（機械可驗）:
        1. `ls -d skills/*/ | wc -l` → **9**（8 個現行 skill ＋ `_deprecated/`）；`ls -d skills/_deprecated/*/ | wc -l` → **5**。
        2. `skills/root-cause-table/SKILL.md` 仍在原處（`test -f` 成立）。
        3. 移動的 5 個檔案內容**逐位元相同**：`git diff --cached -M --name-status` 對這 5 個顯示 `R100`（純 rename、零內容變更）。
        4. `python3 .claude/hooks/doctor.py` → **健檢通過**，且 skills 同步行回報 **9 個 skill**。
        5. 部署層對稱：`diff -r skills/_deprecated ~/.claude/skills/_deprecated` 空輸出；`ls -d ~/.claude/skills/*/ | wc -l` → **9**。
        6. `tests/test_agent_refs.py` 的 diff **只移除 `eval-scorer` 例外條目相關行**（含其註解），`EXCEPTION_LIST` 以外的判準、掃描邏輯、測試案例零改動。
        7. `python3 -m unittest discover -s tests` → `Ran 162 tests ... OK`，無新增失敗（含 `tests/test_agent_refs.py` 與 `tests/test_docs_consistency.py`）。
        8. 反向驗證（證明移除例外是收緊）：暫時把 `skills/_deprecated/eval-scoring/` 移回 `skills/eval-scoring/`，跑 `python3 -m unittest tests.test_agent_refs` 須 **FAIL**（`eval-scorer` 重新進入掃描且已無例外豁免）；還原後 PASS。貼出兩次輸出。
      情境: 汰除歸檔（結構區隔）＋測試掃描來源同步
      備註: 移動與測試同步**刻意同一 item 同一 diff**——移動是因、測試紅燈是果，拆開會讓中間狀態必然紅燈。DoD 8 是本 item 的鑑別力驗證：若移除例外後反向操作仍綠，代表主檢查沒真的涵蓋 `eval-scorer`，那移除就是放寬而非收緊。
