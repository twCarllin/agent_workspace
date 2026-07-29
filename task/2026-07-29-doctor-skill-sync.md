# Task：doctor.py 增加 skills 部署同步健檢（run_id: 2026-07-29-doctor-skill-sync）

> Tier 1 精簡路徑。本檔自足：不依賴任何對話上下文。
> 背景（需求原文）：為 `.claude/hooks/doctor.py` 增加一項部署健檢，比對 repo 的 `skills/` 與部署層 `~/.claude/skills/` 的**存在性與內容一致性**，並為 `doctor.py` 建立測試檔（目前零測試覆蓋）。現況缺口：2026-07-29 發現有 6 個 skill 只存在於 `~/.claude/skills/` 而未納入 repo 版控；另有 SKILL.md 修改後需手動 `cp` 同步到部署層，漏同步時執行期會讀到舊版。兩類漂移目前完全靠人工發現。

## Task 1：skills 同步健檢 ＋ doctor.py 測試覆蓋

- [x] **item 1**：`doctor.py` 新增 `check_skills_sync()` 健檢並接進 `main()`，同一份 diff 附 `tests/test_doctor.py`
  - **files**：`.claude/hooks/doctor.py`（修改）、`tests/test_doctor.py`（新增）
  - **不得修改任何既有測試檔**（並行硬前提：既有測試只增不改）
  - **DoD**：
    1. `doctor.py` 有一個可注入路徑的純函式 `check_skills_sync(repo_skills_dir, deploy_skills_dir)`，回傳 `(ok, issues)` 兩個字串 list，沿用既有 `ok`／`issues` 累積與 `[doctor] OK:` ／`[doctor] ISSUE:` 輸出慣例（不另起輸出通道、不自己 print、不自己 sys.exit）
    2. `main()` 呼叫該函式，repo skills 目錄由 `doctor.py` 所在位置推導（`<repo root>/skills`，repo root ＝ `.claude/hooks` 的上上層），部署層沿用既有 `~/.claude/skills` 變數
    3. 健檢能分辨三種漂移並各自產生獨立 issue 訊息：①repo 有、部署層沒有（未部署）②部署層有、repo 沒有（未納入版控）③兩邊都有但內容不同（未同步）
    4. `~/.claude/skills` 不存在、或 repo 無 `skills/` 目錄時 **優雅略過**（回傳空 issues ＋一行說明性 ok），不拋例外、不讓 `doctor.py` 崩潰
    5. `tests/test_doctor.py` 全部用 `tempfile.TemporaryDirectory()` 建構受控 fixture，**零處引用執行機器上真實的 `~/.claude/skills`**（換一台機器結果須相同）
    6. `python3 -m unittest discover -s tests` 無新增失敗；`python3 .claude/hooks/doctor.py` 在本 repo 實跑通過（repo `skills/` 與 `~/.claude/skills/` 目前同為 13 個目錄、內容一致）
  - **行為契約表**：

| 情境 | 輸入（repo_skills_dir / deploy_skills_dir） | 預期輸出 |
|---|---|---|
| 完全一致 | 兩邊同名目錄、同內容 | issues 空；ok 含「一致」與數量 |
| repo 有、部署層無 | repo 多一個 `foo` | issues 恰 1 條，內容含 `foo` 與「未部署」語義 |
| 部署層有、repo 無 | 部署層多一個 `bar` | issues 恰 1 條，內容含 `bar` 與「未納入版控」語義 |
| 兩邊都有、內容不同 | 同名 skill 的 `SKILL.md` 內容相異 | issues 恰 1 條，內容含該 skill 名與「內容不同步」語義 |
| 內容差異在巢狀子目錄 | 同名 skill 的 `references/x.md` 相異 | 同上，須偵測到（比對須遞迴） |
| 部署層目錄不存在 | deploy 路徑不存在 | issues 空；ok 含「略過」說明 |
| repo 無 skills/ | repo 路徑不存在 | issues 空；ok 含「略過」說明 |
| 邊界：dotfile 干擾 | 一邊多一個 `.DS_Store` | 不視為漂移（issues 空） |

  - **預估**：~60 行實作 ＋ ~90 行測試
