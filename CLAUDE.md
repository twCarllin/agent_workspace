：# CLAUDE.md

## 部署規則（最重要）

- **禁止** 未經本地測試就直接部署到遠端
- 任何程式碼變更，必須先在本地端驗證功能正常後，才能 commit 和部署
- 部署前必須確認 build 成功（前端 `vite build`、後端模組載入）
- 部署指令 `./deploy/deploy.sh` 只在使用者明確要求時才執行

## 資料庫操作原則

- 測試時使用獨立的 test database，不可動到 dev 或 prod 資料

## Eval Flow

**這個 flow 利用 model:claude-sonnet-4-6**：
當我要求 review + fix 時，執行以下循環（每輪結果寫入 `eval_state.json`）：

1. 呼叫 `code-writer` subagent 產出程式碼
2. 將變更檔案 `git add` 進 staging area（確保 code-reviewer / eval-scorer 可透過 `git diff --cached` 讀取）
3. 呼叫 `code-reviewer` subagent 審查，解析 🔴 重大問題
   - 如果有 🔴：根據建議修正（或呼叫 `code-writer`），重新 `git add` 後再次呼叫 `code-reviewer` 驗證
4. 🔴 清零後，呼叫 `task-verifier` subagent 確認功能完整
   - 比對 task.md vs 實際 diff（子任務完成、DoD 達成、無 scope 偏移）
   - 如有遺漏，修正後回步驟 3
5. 呼叫 `eval-scorer` subagent 獨立打分（讀取 `git diff --cached`），結果 append 進 `eval_state.json`

### Subagent 呼叫原則（省 token）

- **code-reviewer / task-verifier / eval-scorer** 需要讀取程式碼變更時，**必須在 prompt 中指示使用 `git diff --cached`**（Bash 工具），不要用 Read 逐檔讀取完整檔案。`git diff` 只回傳變更部分，token 消耗遠低於讀整檔。
- **auto-mode 開啟時**：這 3 個 agent 可以放背景執行（`run_in_background: true`），Bash 會自動批准。
- **非 auto-mode 時**：這 3 個 agent 必須用前景執行，讓使用者能批准 Bash 權限。不可放背景執行（背景 agent 無法彈出權限確認，會導致 Bash 被拒絕）。
- **retro / task-reviewer** 等不需要 Bash 的 agent：可隨時放背景執行。
6. 判斷分數：
   - **score >= 6** → git commit，清除 `eval_state.json`，結束
   - **score < 6 且 rounds < 2** → 根據評分報告生成改進 brief，回步驟 1
   - **score < 6 且 rounds == 2** → 讀取 `eval_state.json` 生成完整報告，回報使用者
7. **有條件** 呼叫 `retro` subagent：
   - code-reviewer 有 🔴 重大問題 → 修正後 commit 前呼叫 retro
   - score < threshold（需要多輪改進）→ 最終 commit 前呼叫 retro
   - code-reviewer 無 🔴 且 score 一次通過 → **不呼叫 retro**（無需回顧）

### eval_state.json 格式

```json
{
  "task_id": "task 簡短描述",
  "threshold": 6,
  "sub_tasks": [
    {
      "id": 1,
      "name": "子 task 名稱",
      "status": "passed | failed | in_progress",
      "warning": false,
      "rounds": [
        {
          "round": 1,
          "quality_score": 0,
          "dimensions": {
            "Clarity": 0,
            "Completeness": 0,
            "Testability": 0,
            "Non-functional": 0,
            "Technical_constraints": 0
          },
          "brief_sent_to_writer": "改進摘要（score < threshold 時填寫）"
        }
      ]
    }
  ],
  "status": "in_progress | completed | failed"
}
```

### eval_state.json 操作規則

- **開始任務時**：建立 `eval_state.json`，填入 `task_id` 與 `sub_tasks` 結構
- **每輪評分後**：將 `eval-scorer` 的結果 append 到對應 sub_task 的 `rounds` 陣列
- **score < threshold**：在該 round 的 `brief_sent_to_writer` 填入改進摘要
- **sub_task 通過**：將該 sub_task 的 `status` 設為 `"passed"`
- **sub_task 2 輪未過**：`status` 設為 `"failed"`，`warning` 設為 `true`
- **全部完成且通過**：頂層 `status` 設為 `"completed"`，commit 後清除檔案
- **有任一 failed**：頂層 `status` 設為 `"failed"`，回報使用者

## Task Principle

- 任務檔案放在 `task/` 資料夾，以日期命名：`task/YYYY-MM-DD.md`
- 每次新增或讀取任務時，使用**當天日期**的檔案（例如 `task/2026-04-18.md`）
- 舊的 `task.md` 僅作為歷史紀錄保留，不再新增任務到該檔案
- 呼叫 subagent 完成任務
- 標記任務創建時間
- 可以平行化的任務，標註為可以 [P] 代表可以平行化執行
- task 完成後，標記為 [x] 代表任務完成
- **task 檔案有新增任務後，必須呼叫 `task-reviewer` subagent 審查**，確認描述清楚、拆分合理、技術限制已標註，才可以開始執行任務
- **task 所有子任務完成後，必須呼叫 `task-verifier` subagent 驗證**，確認實作與描述一致，才可以 commit

## Subagent Principle

- 工作完成後，如果是從 task 檔案獲取任務，在 eval-score 完成後，要到對應的 task 檔案將任務標記為完成

## 部署準備

- 部署前檢查潛在風險並告知，確認後才可以部署
- 部署前檢查 DB 相關操作可能影響，確認後才可以部署
