# Task：文件引用的 subagent 存在性測試（run: 2026-07-29-agent-ref-test）

- run_id：`2026-07-29-agent-ref-test`
- Tier：1（`spec_inline` 見 `run/2026-07-29-agent-ref-test.json`）
- 背景（自足）：`tests/test_docs_consistency.py` 目前檢查三件事——文件引用的 hook script 路徑存在、文件引用的 skill 存在、agent frontmatter 宣告的 skill 存在。**沒有任何測試檢查「被文件引用的 subagent 本身是否存在於 `.claude/agents/`」**。實際缺口：`skills/eval-scoring/SKILL.md` 通篇依賴 `eval-scorer` subagent，但 `.claude/agents/eval-scorer.md` 已於 run `2026-07-17-remove-eval-scorer` 刪除，全套測試全綠仍抓不到這個懸空引用。
- 硬性範圍限制（並行模式前提「既有測試只增不改」）：本 run **只能新增 `tests/test_agent_refs.py`**，不得修改任何既有檔案（含 `tests/test_docs_consistency.py`）。

## Task 1：新增 agent 引用存在性測試

### [x] Item 1（完成）：`tests/test_agent_refs.py`（~130 行）

- files：`tests/test_agent_refs.py`（新增，唯一允許動的檔案）
- 掃描來源：`skills/*/SKILL.md`、`.claude/agents/*.md`、`CLAUDE.md`、`README.md`（與 `tests/test_docs_consistency.py` 的 `MD_FILES` 同一組來源，但本檔自行定義、不 import 該檔）
- 判準（引用形式，**兩種**，皆須在檔內以註解說明取捨理由）：
  1. 反引號／粗體包裹的名稱後接 `agent`／`subagent`（例：`` `code-writer` subagent ``、`` **`usage-analyzer`** subagent ``）——專案慣用寫法，零誤判
  2. 路徑形式 `.claude/agents/<name>.md`——語義無歧義
  - 明確**不**採納：任何裸名字後接 agent／subagent 的形式。單字形式會命中 `item agent`／`spawn agent`／`cd agent` 等散文；帶連字號形式原列為判準 3（見下方仲裁記錄），實測遭推翻後移除
- **仲裁記錄（主 flow，第 1 輪審查後）**：原判準 3「裸的帶連字號識別字後接 agent／subagent」立論為「帶連字號的 token 不是英文散文」，經 code-reviewer 指出並由主 flow 以 staged 原碼實測推翻——`long-running agent`／`built-in agent`／`user-facing agent`／`multi-purpose subagent`／`real-time agent` 全部命中，即任何人日後在文件寫一句英文散文就會使測試紅燈。裁決：**移除判準 3**，契約表對應 row 由「判為引用」改為「不判為引用」。核心價值不受損——實際死引用 `eval-scorer` 由判準 1 在 `skills/eval-scoring/SKILL.md` 命中（已實測：清空例外清單後主檢查仍 FAIL 於 `eval-scorer`）
- 已知例外清單：`eval-scorer`（真實死引用，`skills/eval-scoring/SKILL.md` 依賴它但 agent 已移除；待汰除，於清單附註解說明）
- DoD：
  1. `python3 -m unittest tests.test_agent_refs -v` 全綠
  2. 主檢查會在**移除例外清單後**抓到 `eval-scorer`（即例外清單真的在承擔攔截，不是判準被放寬到失效）
  3. 例外清單有 hygiene 測試：清單內的名字若「已存在於 `.claude/agents/`」或「文件裡已無人引用」→ 測試失敗，逼使清單被清理，不會爛在原地
  4. 有反向（negative）判準測試：`item agent`／`spawn agent` 等散文不得被判為引用
  5. 有非空性（non-vacuous）測試：掃描結果必須抓到既有的活引用（如 `code-writer`、`task-decomposer`），防「判準寫壞成永遠零命中」的假通過
  6. 不修改任何既有檔案（`git diff --cached --name-only` 僅含 `tests/test_agent_refs.py` 與本 run 的 manifest／task 檔）
  7. 全套 `python3 -m unittest discover -s tests` 相對 baseline 無新增失敗

### 行為契約表（仲裁基準）

| 輸入（文件中出現的字串） | 預期判定 |
|---|---|
| `` `code-writer` subagent `` | 判為引用 `code-writer`（存在 → 通過） |
| `` **`usage-analyzer`** subagent `` | 判為引用 `usage-analyzer`（存在 → 通過） |
| `.claude/agents/code-writer.md` | 判為引用 `code-writer` |
| `` `eval-scorer` subagent ``（現況存在於 `skills/eval-scoring/SKILL.md`） | 判為引用；因在例外清單而不 fail |
| `eval-scorer subagent`（裸名帶連字號） | **不**判為引用（第 1 輪審查後仲裁改判，理由見上方仲裁記錄） |
| `item agent`／`spawn agent`／`cd agent` | **不**判為引用（邊界：裸單字不採納） |
| `retro agent`（裸單字、真引用） | **不**判為引用（邊界：已知且接受的漏抓） |
| `long-running agent`／`built-in agent`／`multi-purpose subagent` | **不**判為引用（邊界：英文複合形容詞是散文，不是引用） |
| `` `Explore` subagent ``／`` `Plan` agent ``（大寫開頭的內建 agent） | **不**判為引用（第 2 輪審查後仲裁增列：判準 1 的名字限小寫，理由是專案 agent 命名慣例即小寫連字號；放寬大小寫會讓文件提到 Claude Code 內建 agent 時誤判紅燈） |
| `` `code-writer` SubAgent ``／`` `code-writer` AGENT ``（關鍵字大小寫變化） | 判為引用（大小寫寬容只給關鍵字，不給名字） |
| 例外清單內的名字其 agent 檔已存在 | hygiene 測試 fail（要求清掉例外） |
| 例外清單內的名字文件裡已無引用 | hygiene 測試 fail（要求清掉例外） |
