## Baseline（run 的測試基準，第一次產品修改前建立）

```
python3 .agent-flow/scripts/test_baseline.py baseline
```

- **全套測試指令從 manifest 的 `test_command` 讀**（single source of truth；`--cmd` 僅供覆寫）。manifest 尚無此欄時，先確認指令並寫入 manifest 再跑——不要每個 run 各猜一套，baseline 與 check 範圍不一致就會出現「無關的既有失敗」
  - **`test_command` 須指定專案直譯器**（專案有虛擬環境時，寫成 `.venv/bin/python3 -m pytest` 之類，不要用裸 `python3`）——系統直譯器缺專案套件會讓整批測試 import 失敗、被誤記為既有 `stable_failures`（幻影欠帳）。baseline 偵測到「有 `.venv/bin` 但 cmd 未用它且有 stable 失敗」時會於 stderr 印錯配警示（僅提醒、不改執行環境）
  - **`test_command` 須為完整組指令**：專案把測試分成日常組／完整組時（pytest marker、conftest 白名單等），manifest 寫**完整組**——日常組是開發期快速回饋，不當 gate（日常組白名單會讓全套靜默縮水而收尾檢查無人察覺）
- **來源前置**：第一次產品修改前建立。須有 Git HEAD，tracked／staged／untracked 產品輸入乾淨；只有 `eval_state.json`、`run/` 的 JSON／JSONL／log 與 `task/`、`spec/` 的 Markdown 等明確流程產物不阻擋。測試前、確認重跑前與結束後核對 HEAD／產品輸入，漂移不發布可信基準。不自動 stash、reset、建 Docker 或 worktree。
- **穩定失敗要二次確認**：第一次有可辨測試 ID 的失敗時，在同一修改前來源重跑一次，只把兩次交集記為 `stable_failures`；首次成功只跑一次。unittest 以具體案例 ID 判定，`FAILED (failures=1)` 摘要不是測試 ID。
- **執行問題不能扣除**：逾時（含命令退出碼 124）、無法解析的 `__suite__`、測試程序啟動／執行錯誤永不列 stable，也不能讓 check 通過。每次執行預設上限 300 秒；`--timeout <秒數>` 可指定 `0 < 秒數 <= 86400`，baseline 與 check 必須使用相同上限。逾時清理本次程序群組，不終止其他程序；输出收尾與 wait 各最多再等 0.25 秒。自行脫離群組的後代不在清理承諾內，其持有 pipe 不得使工具無限等待。分類、退出碼、實際 stdout／stderr 與執行時間保存在 observations；baseline 執行問題另存 `run/<run_id>.baseline_execution.json` 並回傳非零。
- **可信沿用**：schema 2 必須具有相同的乾淨來源前後紀錄、確認觀測、命令、環境指紋與上限。跨 run 自動沿用還須 HEAD 相同；已有產品修改只能沿用上述可信檔，不能重建。check 可沿用目前 HEAD 祖先的可信基準，保留相關測試 `--cmd` 範圍，記錄實際命令並按同一可辨 ID 扣除。舊 schema、來源不明、sentinel 或觀測不符者明確拒絕，不能補欄位升格。
- **環境範圍**：指紋涵蓋環境變數（排除 shell 易變欄位）、執行此工具的 Python 版本／路徑、平台與工作目錄，只存雜湊。它不能證明外部服務或套件內容未變；已知環境改變須在乾淨產品來源用 `--fresh` 重建。
- **修改後缺可信基準**：保留現場，使用另外保留的乾淨起始版本另行取證與比較；不同目錄的基準不能直接搬回沿用，不把目前失敗宣稱為既有。若不需要扣除既有失敗，主 flow 可直接用 `run_verify.py` 執行必要驗證，要求零失敗；不為補基準自動建立額外環境。
- 寫入 `run/<run_id>.test_baseline.json`（`run_id` 自動讀 `eval_state.json`）。此檔是冷溯源檔，**留在工作目錄、永不清除；不進版控**（處置的單一枚舉點住 eval-flow SKILL.md step 6 子項②，改任一端時對照另一端）。`stable_failures` 就是本 run 進場時的**既有欠帳快照**
- **既有壞測試 = 記錄級欠帳，不是攔截級**：與 hotfix `debt` 不同——不擋新 run、本 run 不修（修它是 scope 偏移），但 retro 時彙報數量與清單，讓債看得見
- 無任何測試框架的專案不建 baseline，改走 test-strategy skill「零測試專案」節
