# evals/ — eval-flow 行為評測

量「模型拿到需求後照不照 skill 走」。每個子目錄一個情境：`prompt.md`（給模型的需求原文）、`check.py`（對 fixture 做純檔案斷言），需要前置現場者另有 `setup.py`。

**不是 pytest 的一部分**：每次執行是付費、非確定性的真實 agent session。`tests/test_evals_suite.py` 只做靜態結構檢查。

## 跑

```
python3 .claude/hooks/skill_eval.py --dry-run          # 只印計畫，不花錢
python3 .claude/hooks/skill_eval.py                    # 預設：runs 1、累計上限 3 美元（約只夠一個情境，見下）
python3 .claude/hooks/skill_eval.py --case resume-interrupted --keep-fixture
python3 .claude/hooks/skill_eval.py --runs 3 --max-cost-usd 10
```

跑之前先 `./init.sh`：評測載入的是 `~/.claude/skills/` 的部署版，runner 開場會比對並警告不一致。

**預算怎麼讀**：實測單情境 1.6–2.6 美元，預設上限 3 美元**只夠跑完約一個情境**（依字母序先跑 `resume-interrupted`），其餘記「成本上限觸及」exit 2。要三個都跑用 `--max-cost-usd 8`。上限是近似值：剩餘預算會當成該 session 的 `--max-budget-usd`，拿不到成本數字（超時、輸出不可解析）時保守記滿該預算；被切斷的 session 記「預算切斷（不計行為）」而不是 FAIL。

## 讀結果

stdout 每情境印 `PASS|FAIL <斷言> — <原因>` 與成本；全部寫到 `evals/results/<時間戳>.json`（不進版控）。exit 0 全過、1 有 FAIL、2 觸及成本上限（部分結果）。

**首跑分數是量測，不是回歸基線**。同一情境兩次結果可能不同；`--runs 3` 的通過率穩定後才拿來比。

## 情境

| 目錄 | 量什麼 |
|---|---|
| `tier1-routing` | 理由碼空集合的小需求 → 判 Tier 1、載入 eval-flow、manifest 的 `tier`／`tier_rationale` |
| `tier1-hitl-stop` | 同類需求 → 建 task 檔後停在輕量 HITL，未改 `.py`、未 commit |
| `resume-interrupted` | 預造中斷現場（task 1 passed、task 2 reviewing）→ 報對 run_id、從重派 checker 續跑、不重跑 task 1。此即 TODO 第 15 節的 Game day 載體 |

`check.py` 綁住現行欄位名（檔頭有列）。改 manifest／eval_state 欄位時一併改情境，否則評測會把過期當退化。
