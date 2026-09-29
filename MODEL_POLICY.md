# Model 政策表（單一枚舉點）

> agent→model 指派的**唯一枚舉點**。各 agent 定義檔（`.claude/agents/*.md`）frontmatter 的 `model` 欄是執行端載體（Claude Code harness 實際讀取處），`tests/test_model_policy.py` 強制兩者一致——**改 model 時，本表與對應 frontmatter 必須同一個 diff 改齊**，只改一邊測試會紅。
> frontmatter 的行內註解是現場註記；指派理由的敘述以本表為準。
> headless 派工（`.claude/hooks/dispatch.py` → `claude -p --agent <role>`，2026-09-29 起）由 `--agent` 讀同一份 frontmatter，本表仍是唯一枚舉點；Codex 後端另讀 `.codex/agents/*.toml`（`install_codex.py` 的 `CODEX_MODELS`）。

| agent | model | 指派理由 |
|---|---|---|
| code-reviewer | claude-sonnet-5-5 | 升級路徑專用（checker 四類觸發之一成立時派用）＋高風險手動觸發；2026-09-29 由 opus-4-8 改（使用者裁決全部 sonnet-5-5），與 writer 的去相關化改由 session 層承擔（見約束節） |
| code-writer | claude-sonnet-5-5 | 近 Opus 級 coding（2026-09-29 由 sonnet-5 升級） |
| impact-analyzer | claude-sonnet-5-5 | 影響面盤點＝跨模組推理密集；2026-09-29 由 opus-4-8 改（使用者裁決） |
| retro | claude-sonnet-5-5 | 歸因提煉為中等推理量，不需最強檔（2026-09-29 由 sonnet-4-6 升級，與 writer 同檔） |
| task-decomposer | claude-sonnet-5-5 | 拆解＝規劃判斷密集，拆錯整條 flow 重跑；2026-09-29 由 opus-4-8 改（使用者裁決） |
| task-verifier | claude-sonnet-5-5 | checker（審查層預設位，2026-09-05 起）——憑據逐條核對；2026-09-29 由 haiku-4-5 升級（使用者裁決；實測 haiku 首輪曾 1 turn 無憑據交付）；假放行率為回退依據（v3 回退機制見 retro/BUGLOG.md） |
| usage-analyzer | claude-sonnet-5-5 | 情境盤點＝判斷密集；2026-09-29 由 opus-4-8 改（使用者裁決） |

## Codex 政策表

> Codex 後端（`dispatch.py --backend codex`／manifest `harness: "codex"`）的 agent→model 指派。執行端載體＝`install_codex.py` 的 `CODEX_MODELS`（安裝時產生 `.codex/agents/<role>.toml` 與 `.agent-flow/CODEX_MODEL_POLICY.md`；dispatch.py 讀 toml 的 `model`／`model_reasoning_effort`）。**改 model 時本表、`CODEX_MODELS`、repo 內 `.codex/agents/*.toml` 三處同一個 diff 改齊**，`tests/test_model_policy.py` 強制三方一致。

| role | model | reasoning effort | 指派理由 |
|---|---|---|---|
| code-writer | gpt-6-sol | medium | 實作＝量大、機械偏多 → 一般檔；與 reviewer（astra）異族 |
| code-reviewer | gpt-6-astra | medium | 審查＝判斷密集 → 強檔；與 writer 異族（去相關化） |
| task-verifier | gpt-6-luna | high | checker 憑據逐條核對＝機械式 → 快檔，以高 effort 補遵從；假放行率為回退依據 |
| task-decomposer | gpt-6-astra | medium | 拆解＝規劃判斷密集，拆錯整條 flow 重跑 → 強檔 |
| usage-analyzer | gpt-6-astra | low | 情境盤點＝判斷密集 → 強檔；low effort 控成本（具名問題觸發、範圍窄） |
| impact-analyzer | gpt-6-astra | low | 影響面盤點＝跨模組推理 → 強檔；low effort 同上 |
| retro | gpt-6-sol | low | 歸因提煉為中等推理量，不需最強檔 |

- 主 session（coordinator）model 不入表，沿用 `~/.codex/config.toml` 預設，與 Claude 端「主 session 不入表」一致
- model id 可用性：2026-09-29 以 `dispatch.py --backend codex` 實跑 task-verifier（gpt-6-luna）驗證，見 run `2026-09-29-codex-model-policy` 留痕；其餘 id 未逐一實測

## 約束

- **去相關化（session 層，2026-09-29 起）**：`code-writer` 與 `code-reviewer` 一律**分別派工**——headless 派工（eval-flow「派工機制」節）下兩者是不同子 session、不共用 context，reviewer 只讀 staged diff 與契約，不讀 writer 的推理過程。原「model 必須異族」硬約束（出生證：同一顆腦互審抓不到共同盲點）於 2026-09-29 由使用者裁決廢除（run `2026-09-29-all-sonnet55`，Claude 端全部 sonnet-5-5），對應測試 `test_writer_reviewer_families_differ` 隨之刪除；若日後 reviewer 漏抓率上升，重開此約束的證據住 `retro/BUGLOG.md`。**Codex 表仍守異族**：writer 與 reviewer 的 model id 必須不同（sol vs astra），`tests/test_model_policy.py` 強制。
- 指派準則沿用 eval-flow skill「Model 指派原則」：推理／判斷密集的規劃與審查 → 強 model；機械式、量大的執行 → 快 model。
- 本表只管 subagent；主 session／skill 執行（如前置 1 風險分析）沿用主 session model，不入表。
