# GAMEDAY — 中斷恢復演練記錄

> 每次演練一節，新的加在最下面。演練載體：`evals/resume-interrupted/`（`python3 .claude/hooks/skill_eval.py --case resume-interrupted --keep-fixture`）。
> 來源：TODO 第 15 節「Game day：沒演練過的恢復程序等於不存在」。

## 演練 1 — 2026-10-03（run `2026-10-03-skill-evals`）

### 演練設計

- **中斷現場（fixture，不 kill 真 run；使用者裁示）**：暫存目錄 `git init`，以 `cp` 複製 repo 現檔的 `CLAUDE.md`、`.claude/`、`skills/`（首跑時尚未複製 `.gitignore` 與 `retro/`，見缺口 1、2）。`setup.py` 造出 Tier 2 run `2026-10-01-greeting-module`：manifest `status: in_progress`／`phase: decomposed`／`hitl_confirmed_at` 已記；`eval_state.json` 有 task 1（`passed`／`done`／`checked_by: checker`）與 task 2（`in_progress`／`step: reviewing`）；task 2 的測試檔在 staging、未 commit。
- **恢復者拿到什麼**：一個全新的 headless session（`claude -p`），cwd 是 fixture，需求只有一句「接續上次的 run。」。沒有任何對話記憶，只有檔案。
- **期望（依 `eval-flow-resume` skill）**：Step 1 掃到唯一的 in_progress manifest 並與 `eval_state.json` 互相印證；Step 2 `phase: decomposed` → 進循環內恢復；Step 3 找到 task 2 `step: reviewing` → 一律重跑該輪、重派 checker，從循環步驟 3 起；已 `passed` 的 task 1 不重跑；恢復後第一件事回報現況摘要。

### 實際觀察

成本 2.61 美元、26 輪、單次 session 跑完整條恢復到 commit。恢復者回應原文摘錄：

> Run `2026-10-01-greeting-module` 已恢復並完成收尾。
> **恢復點** Task 2 farewell 卡在 step=reviewing，首輪。staged 只有測試檔，`farewell()` 實作已隨 Task 1 的 commit 41d5a6b 進入 HEAD。Writer 工作報告未落檔，依 resume 規則重跑該輪、重派 checker。
> **審查** Checker（task-verifier）升級①③：writer 報告缺席、sabotage 自檢證據缺席。改派 code-reviewer 全 diff 審：零 🔴、零 🟡，完成度 3/3。引文核實 2 條全 ok。記帳：`review_reds=0`、`checked_by=reviewer:①`、`verify_passed=true`。
> **Step 5／6** baseline stable 0；test_lint PASS；check PASS（`sub_task_2`）；收尾全套 check PASS。已歸檔 `.eval.json`，eval_state.json 已清除。Commit `fd6b771 ADD: farewell(name)`，manifest 已 `completed`。升級輪零 🔴，依規則不派 retro。
> **需要你知道的事** prepare gate 把 untracked 的 `run/` 算進程式樹快照，run_verify 自己回寫 manifest 就會失配。我在本機 `.git/info/exclude` 加了 `run/` 與 `__pycache__/` 才通過。建議專案 `.gitignore` 正式加上 `run/`。doctor 兩項問題未處理：`retro/RETRO.md` 不存在，後續 run 的知識前置會落空。

逐條對照 resume skill 的期望：

| resume skill 期望 | 觀察 | 判定 |
|---|---|---|
| Step 1 定位唯一 in_progress run，與 eval_state 互證 | 報出正確 run_id；events 顯示直接從 task 2 續跑 | 符合 |
| Step 2 `phase: decomposed` → 循環內恢復 | 未重做前置、未重分拆 | 符合 |
| Step 3 `reviewing` → 重派 checker、從步驟 3 起 | fixture `run/*.dispatch.jsonl`：task-verifier（0.21 美元）→ 升級 code-reviewer（0.18 美元） | 符合 |
| 已 `passed` 的 task 1 不重跑 | 歸檔 `.eval.json` 中 task 1 仍 `passed`／`done`／`checked_by: checker`，未改 | 符合 |
| 恢復後先回報現況摘要再動作 | headless 單次回應中「恢復點」節在最前，但無法從單一回應判斷它是「先報再做」還是「做完一起報」 | 不可判（headless 限制） |
| hook gates 照常生效 | prepare gate 在 fixture 內真的擋了一次（程式樹快照失配） | 符合（gate 有效，見缺口 1） |
| 收尾順序：歸檔 → 清 eval_state → token 用量 → commit 附 Run-Id → finalize | events：set-review → set-verify → testing → set-test → done → verify_cmd full_suite → archive → commit；manifest `completed`、HEAD message 含 `Run-Id: 2026-10-01-greeting-module` | 符合 |

**S3 情境的機械斷言**（修正後重判首跑 fixture）：5 條全 PASS——回應含 run_id、含重派 checker／步驟 3、task 1 未重跑、新 commit 掛 Run-Id trailer、manifest `completed`。

### 程序缺口

| # | 缺口 | 歸類 | 處置 |
|---|---|---|---|
| 1 | fixture 沒複製 `.gitignore`，`run/` 成為 untracked 進入 prepare gate 的程式樹快照，恢復者得自己改 `.git/info/exclude` 才能 commit。真實 repo 有 `.gitignore`，這是情境設計問題不是流程問題；但它順帶證明 gate 在 fixture 內生效 | 情境設計 | **已修**：`skill_eval.py` 的 `FIXTURE_SOURCES` 加 `.gitignore` |
| 2 | fixture 沒複製 `retro/`，知識前置落空（恢復者 doctor 報 `retro/RETRO.md` 不存在） | 情境設計 | **已修**：`FIXTURE_SOURCES` 加 `retro` |
| 3 | 在 `reviewing` 恢復時 checker 升級（演練 1 觀察到，n=1）：writer 工作報告不落檔，checker 輸入集缺它與 sabotage 證據，依①③升級。resume skill 的「已知缺陷」只列了輪數低估兩條，沒寫這條；接手者可能誤以為升級是異常、去補造 writer 報告 | 流程文件 | **已修**：`skills/eval-flow-resume/SKILL.md` 已知缺陷加第 3 條，以「演練 1 觀察到」的描述語氣寫（n=1，不寫成規則），並提醒不要補造 writer 報告 |
| 4 | fixture 的 commit 1 誤含 `farewell()` 實作，恢復者一眼指出「staged 只有測試檔」。現場不真，恢復者的判斷被迫繞過它 | 情境設計 | **已修**：`setup.py` 改為 commit 1 只含 `greet`，`farewell` 實作與測試一起留在 staging |
| 5 | 我的 S3 斷言寫錯兩條：「未自行 commit」——恢復後把 run 跑完並 commit 是正確行為；「eval_state.json 仍可讀」——run 收尾後 eval_state 依規則被歸檔清除，正確行為反而讓它消失。首跑的 2 條 FAIL 全是這兩條斷言造成 | 情境設計 | **已修**：commit 斷言改為「有新 commit 時須掛 Run-Id trailer 且 manifest `completed`；無 commit 時 manifest 須仍 in_progress／ready_to_commit」；task 1 狀態改為從 `eval_state.json` 或歸檔 `.eval.json` 擇一讀取。對保留的首跑 fixture 重判 5／5 PASS（手動執行 `check.py`，輸出見上「實際觀察」末段；未另產 results JSON） |
| 6 | checker 與 reviewer 報告皆缺首行戳記行（advisory），與主 repo 歷次 run 相同 | 既有觀察 | **不處理**：advisory 不退件是既定裁決；累計次數供日後 agent 定義調整 |
| 7 | 恢復者在 fixture 內自行改了 `.git/info/exclude`。在 fixture 無害；在真 repo 這是未經確認改 git 設定 | 流程行為 | **列 TODO**（`TODO.md` 第 15 節「resume 守則候選」條）：是否在 resume skill「恢復守則」加一句「不得為通過 gate 改 git 設定，改回報使用者」——需使用者裁決，不在本 run 自行加規則 |

**實際走到的 step**：resume Step 1、2、3（含 `reviewing` 列）、循環 3→4→5→6、hook prepare gate。**沒走到**：`ready_to_commit` 恢復列、`writing`／`testing` 列、多個 in_progress run 的選擇、`failed`／`aborted` 不自動恢復守則。這些列的恢復程序仍是「寫在紙上、沒演練過」。

**原設想「step 5 中途 kill 真 run」未做**（使用者裁示 fixture 演練）。fixture 演練對「恢復程序讀檔是否足夠」有效；對「真 session 掛掉時 harness 的行為」無效。
