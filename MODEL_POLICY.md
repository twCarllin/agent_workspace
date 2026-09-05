# Model 政策表（單一枚舉點）

> agent→model 指派的**唯一枚舉點**。各 agent 定義檔（`.claude/agents/*.md`）frontmatter 的 `model` 欄是執行端載體（Claude Code harness 實際讀取處），`tests/test_model_policy.py` 強制兩者一致——**改 model 時，本表與對應 frontmatter 必須同一個 diff 改齊**，只改一邊測試會紅。
> frontmatter 的行內註解是現場註記；指派理由的敘述以本表為準。

| agent | model | 指派理由 |
|---|---|---|
| code-reviewer | claude-opus-4-8 | 審查＝判斷密集 → 強 model；與 writer 異族（去相關化） |
| code-writer | claude-sonnet-5 | 近 Opus 級 coding；維持與 reviewer（opus）的異族互審 |
| impact-analyzer | claude-opus-4-8 | 影響面盤點＝跨模組推理密集 → 強 model |
| retro | claude-sonnet-4-6 | 歸因提煉為中等推理量，不需最強檔 |
| task-decomposer | claude-opus-4-8 | 拆解＝規劃判斷密集，拆錯整條 flow 重跑 → 強 model |
| task-verifier | claude-haiku-4-5-20251001 | DoD 逐條對照＝機械式 → 快 model；假通過率為回退依據 |
| usage-analyzer | claude-opus-4-8 | 情境盤點＝判斷密集 → 強 model |

## 約束

- **去相關化（硬性）**：`code-writer` 與 `code-reviewer` 必須**異族**（model id 的家族名不同，如 sonnet vs opus）——同一顆腦互審抓不到共同盲點。`tests/test_model_policy.py` 強制。
- 指派準則沿用 eval-flow skill「Model 指派原則」：推理／判斷密集的規劃與審查 → 強 model；機械式、量大的執行 → 快 model。
- 本表只管 subagent；主 session／skill 執行（如前置 1 風險分析）沿用主 session model，不入表。
