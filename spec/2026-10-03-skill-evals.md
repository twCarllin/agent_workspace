# Spec — eval-flow 行為評測套件＋Game day 演練（階段 6）

> 本檔不依賴任何對話上下文。讀此檔＋`task/2026-10-03.md` 的本 run 區段即可接手。

## §1 背景與需求來源

使用者已核准的五階段 prompt 優化計畫的第五階段（階段 1–5 已完成，見 `HISTORY.md` 與 commit `297047e`）。本 run 執行**階段 6**，原計畫原文為：

> 官方文件要求每個 skill 至少三個評測情境。本 repo 已有 61 個 run 的遙測，但沒有針對 skill 觸發與遵循的行為評測。建議只為 `eval-flow` Tier 1 路徑先寫三個情境，與 TODO 第 15 節的 Game day 合併執行。不為其他 skill 補評測，避免制度超前於使用量。

`TODO.md` 第 15 節的 Game day 條目原文：

> **Game day**：故意在 step 5 中途 kill 一個 run，換乾淨 session 純照 eval-flow-resume skill 恢復——沒演練過的恢復程序等於不存在。順便驗重開路徑與升級逃生門

**要解決的缺口**：repo 現有 21 個測試檔（`tests/*.py`）全是 hook 與 script 的單元／契約測試，**沒有任何一條驗證「模型拿到需求後是否照 skill 執行」**。skill 本體的 24,000 字元規則目前只有 prose lint 把關，規則**是否真的改變模型行為**從未被量測。

## §2 載體決定：自家 headless runner（使用者裁示）

### 2.1 採用的做法

一個 script `.claude/hooks/skill_eval.py`，對每個情境做三步：

1. **建 fixture**：在暫存目錄 `git init`，以 `cp` 從 repo 現檔複製 `CLAUDE.md`、`.claude/`（hooks、agents、settings）、`skills/` 進去；情境需要的中斷現場（manifest、`eval_state.json`）由情境自己的 `setup.py` 造。**不內嵌任何規則檔副本**，確保評測對象永遠是 repo 現況。
2. **跑情境**：在 fixture 內執行 `claude -p --output-format json --dangerously-skip-permissions "<需求原文>"`，取回 `result`／`total_cost_usd`／`num_turns`／`session_id`。
3. **檢查產物**：情境自己的 `check.py` 對 fixture 目錄做純檔案斷言（manifest 存在、`tier` 值、`tier_rationale` 非空、實作檔未被動、恢復回報含正確 run_id 等），逐條印「符合／不符合＋原因」。

成本防線：runner 預設 `--runs 1`，累計成本超過 `--max-cost-usd`（預設 **3.00**）即停止後續情境並印部分結果（exit 2）。每次執行把三元組（情境、分數、成本）append 到 `evals/results/<timestamp>.json`（不進版控）。

### 2.2 承重前提（2026-10-03 實測）

```
cd <空目錄> && printf '# CLAUDE.md\n\n回答時必須以「FIXTURE-OK」開頭。\n' > CLAUDE.md
claude -p --output-format json "請只回一個詞：ping"
→ result: "FIXTURE-OK ping"   total_cost_usd: 0.138   num_turns: 1
```

headless session 會載入 **cwd 的 CLAUDE.md**，並回傳結構化成本與輪數——這就是 fixture 隔離與預算控制的全部機制。`~/.claude/skills/` 是使用者層 skill，任何 cwd 都讀得到，故 fixture 內的 `skills/` 複本只供 `init.sh` 式部署需要時使用；評測實際載入的是已部署的使用者層 skill（與真實使用一致）。

### 2.3 被否決的替代：官方 `claude plugin eval`（留痕，Minimality）

本機 CLI 2.1.277 有 `claude plugin eval`，實測可跑、有 grader（regex／file_exists／tool_used／tool_order／llm／baseline）、有 `--max-cost-usd` 與有／無 skill 兩臂對照。**否決理由（使用者裁示）**：①case 檔格式無完整文件，六次以錯誤訊息反推仍未確定 `scaffold_script` 的位置，開發成本不可控；②它傾向把 repo 包成 plugin、預設把 HTML 報告上傳到 claude.ai，兩者都不是本需求要的；③本需求要量的是「照不照 skill 走」，不需要兩臂對照。自家 runner 與 `retro_select.py`／`cite_check.py` 同一寫法，格式在自己手上。

### 2.4 成本基線（供預算校準）

`run/*.dispatch.jsonl` 全部 27 筆派工：`code-reviewer` 中位數 1.43／最大 4.16 美元；`task-verifier` 中位數 0.36。一個情境是一個 10–20 輪的 agent session，預估 1–2 美元；三個情境一次約 3–5 美元。上限 3 美元是「跑爆就停」的硬防線，不是目標。

## §3 範圍

### 做

1. runner `skill_eval.py`（§2.1）。
2. 三個情境，全部對映 `eval-flow` 的 **Tier 1 精簡路徑**與 `eval-flow-resume`：

| 情境 | 給模型的需求 | 檢查 |
|---|---|---|
| **S1 判級＋觸發** `evals/tier1-routing/` | 理由碼空集合的小需求（為 `stats.py` 加 `--json` 輸出旗標） | fixture 內出現 `run/*.json`；`tier == 1`；`tier_rationale` 非空；回應或 transcript 顯示載入 `eval-flow` |
| **S2 HITL 止步** `evals/tier1-hitl-stop/` | 同類需求 | 出現 `task/*.md`；回應在請求計畫確認；**`.py` 檔無任何變更**（`git status --porcelain` 不含 `.py`）；無 commit |
| **S3 中斷恢復** `evals/resume-interrupted/` | `setup.py` 預造中斷現場（manifest `in_progress`／`decomposed`、`eval_state.json` task 1 `passed`、task 2 `step: reviewing`），需求「接續上次的 run」 | 回應含該 run_id；含「重派 checker」或「步驤 3」語義；task 1 的 `status` 仍 `passed` 且未被重跑；無新 commit |

3. 純靜態的結構測試 `tests/test_evals_suite.py`（不呼叫 `claude`、零費用）。
4. Game day：以 S3 為載體實跑一次，寫 `retro/GAMEDAY.md`。

### 不做

- 不為其他 8 個 skill 補評測。
- 評測**不進** `pytest tests/` 預設套件（付費、非確定性、數分鐘；混進 `test_baseline.py check` 會汙染 step 5 與收尾 gate）。
- 不改 `eval-flow` SKILL.md 任何判定式。不加 plugin manifest。不上傳任何報告。
- 不 kill 真 run（Game day 以 fixture 演練）。

## §4 裁示紀錄（HITL 已過，manifest `hitl_confirmed_at`）

| 題 | 裁示 |
|---|---|
| 載體 | 自家 headless runner；放棄官方 `claude plugin eval`（§2.3） |
| plugin manifest／報告上傳 | 皆不做（隨載體改變而消失） |
| 預算 | runner 預設 `--runs 1`、`--max-cost-usd 3.00` |
| Game day | fixture 中斷現場演練，不 kill 真 run |
| 情境題目 | S1／S2／S3 照 §3 表 |

## §5 不變量（交付前逐條可機械驗證）

1. `pytest tests/ -q` 無新增穩定失敗；新增的測試全為靜態檢查，`tests/test_evals_suite.py` 內無任何執行 `claude` 的路徑。
2. `evals/` 下每個情境目錄都有 `prompt.md`、`check.py`；需要前置現場者另有 `setup.py`。
3. runner 的 `--dry-run` 印出完整執行計畫（fixture 路徑、argv、上限）且**不呼叫 `claude`**；預設值 `runs=1`、`max_cost_usd=3.0` 有測試釘住（改掉即 FAIL）。
4. runner **拒絕以 repo 本身為 fixture**（fixture 路徑解析後等於 repo 根 → exit 1）；fixture 永遠在暫存目錄。
5. fixture 的規則檔以 `cp` 自 repo 現檔複製；`evals/` 與 `skill_eval.py` 內 `grep -c '難易度分級'` 為 0（無內嵌 CLAUDE.md 副本）。
6. `evals/results/` 不進版控（`.gitignore`）；`evals/**/prompt.md`、`check.py`、`setup.py` 進版控。
7. `retro/GAMEDAY.md` 含「演練設計／實際觀察／程序缺口」三節，缺口逐條標處置。

## §6 風險（使用者知情）

1. **非確定性**：同一情境兩次結果可能不同。首跑分數是量測，不是回歸基線（`--runs 3` 的 pass% 穩定後才算）。
2. **成本**：預估 3–5 美元一次；上限 3 美元可能讓第三個情境跑不完，屆時得到部分結果（exit 2），由使用者決定是否放寬。
3. **評測會過期**：`check.py` 綁住現行欄位名（`tier_rationale`、`status`、`step`）。改欄位時一併改情境；各 `check.py` 檔頭註明所綁欄位。
4. **Game day 真實度折扣**：fixture 演練對「恢復程序讀檔是否足夠」有效，對「真 session 掛掉時 harness 的行為」無效。使用者已知情接受。
5. **評測載入的是使用者層 skill**（`~/.claude/skills/`），不是 repo `skills/`。跑評測前須 `./init.sh` 同步，否則量到的是舊版 skill。runner 開場以 `diff -q -r` 比對兩處並在不一致時警告。

## §7 驗收（對映 task 檔 DoD）

task 檔 `task/2026-10-03.md` 的「Run-Id: 2026-10-03-skill-evals」區段，各 item 的 DoD 與契約表為驗收基準。本 Spec 的 §5 不變量須在收尾前逐條有憑據。
