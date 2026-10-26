# 跨工具行為評測

評測模型是否依專案 skill 執行。各案例由 prompt.md、check.py 與選用的 setup.py 組成。fixture 用共用安裝器建立，讀取目前 repo 的規則；不使用個人 skills 副本。

```sh
python3 .agent-flow/scripts/skill_eval.py --dry-run --harness claude
python3 .agent-flow/scripts/skill_eval.py --dry-run --harness codex
python3 .agent-flow/scripts/skill_eval.py --harness claude --case resume-interrupted --keep-fixture
python3 .agent-flow/scripts/skill_eval.py --harness codex --case tier1-hitl-stop --timeout 90
```

未給 harness 時沿用 claude。模型讀專案政策，必要時可用 --model 明確指定；不自動 fallback。CLI 預設保留其權限設定；--permissions unrestricted 是明確完整權限模式。兩種客戶端都需啟用並信任專案 hooks。

Claude 預設累計上限 3 美元，剩餘預算傳給 --max-budget-usd；成本未知時保守占用該預算。Codex CLI 不提供美元預算限制，成本記 null／unknown，--max-cost-usd 不適用；執行以 --runs（預設 1）及 --timeout 限制。

結果存 evals/results/，記 harness、模型、權限、session 與成本狀態。exit 0 全過、1 有失敗或工具錯誤、2 Claude 成本上限造成部分結果。不可解析或 is_error 不進 checker 當正常結果。單次分數是量測，不能當穩定回歸基線。

| 案例 | 驗收 |
|---|---|
| tier1-routing | 判 Tier 1，建立 manifest 與 init 事件 |
| pure-question | 只回答問題，不建立 run 或修改檔案 |
| tier1-hitl-stop | 使用者明示有待裁示問題時，不改實作檔、不提交 |
| resume-interrupted | 從 task 2 reviewing 定位，不重跑已 passed 的 task 1 |
| reuse-existing | 新增收據金額顯示時，正確重用既有美元格式規則，不修改該規則 |

比較實作指引時，`compare_practices.py` 對同一案例、同一 harness、同一模型交替執行兩版指引。它只替換暫存 fixture 的 `.agent-flow/PRACTICES.md`；結果檔記錄兩版指引的雜湊值、案例結果、追蹤檔案的修改行數與執行時間。先從 Git 取出舊版指引。比較通過率、修改行數與耗時前，先確認執行都完成且沒有預算切斷或工具錯誤。單次結果只供檢查流程，不能證明效益。

評估單一步驟是否值得保留時，先固定案例、驗收、模型與權限，只變動該步驟。至少同時計數驗收通過、被攔下的實際錯誤、執行時間與可取得的成本。`evidence_audit.py` 逐對列出品質及時間差；品質相同只表示該案例未顯示差異，不能推論步驟無用。工具／檢查器錯誤、缺配對或缺時間時標為資料不足，不算行為失敗。不同案例或不同模型不可併成單一效益數字。

新 live 結果記錄來源 commit、工作區變更雜湊與乾淨狀態、案例輸入雜湊、runner 雜湊、Python 與 CLI 版本、權限及超時。這些欄位供核對，不保留來源全文；工作區有變更時，單靠雜湊無法重建變更，稽核會標出 `source_clean` 缺口。要精確重跑，需保存相同 commit、工作區變更與外部工具版本。舊結果缺欄時，稽核只報缺項，不補造。`run/` 的驗證快照證明當次輸入與結果，不能取代評測的模型、提示與 CLI 條件。

`evidence_audit.py` 也檢查 `run/*-blocked.md` 是否有重現步驟、根因假設、失敗嘗試與結果、證據位置、待裁決問題。若沒有真實報告，明示無實測交接資料；格式檢查不能證明接手者已成功恢復。

```sh
python3 evals/evidence_audit.py
```

```sh
git show HEAD:.agent-flow/PRACTICES.md > /tmp/practices-before.md
python3 evals/compare_practices.py --baseline /tmp/practices-before.md --runs 3 --dry-run
python3 evals/compare_practices.py --baseline /tmp/practices-before.md --runs 3
python3 evals/compare_practices.py --baseline /tmp/practices-before.md --case tier1-routing --runs 3
```

CLI smoke 用 harness_smoke.py；它量客戶端整合，與完整 skill 行為評測分開。預設預覽；--live 呼叫模型，--trust-local-hooks 僅批准這次由 runner 產生的暫存 Codex hooks。

```sh
python3 .agent-flow/scripts/harness_smoke.py
python3 .agent-flow/scripts/harness_smoke.py --live --trust-local-hooks --timeout 90
python3 -m unittest tests.test_harness_adapter tests.test_harness_flow tests.test_install_transaction tests.test_harness_smoke
```

本地測試不呼叫付費模型，覆蓋安裝、事件轉換、阻擋、失敗處理與恢復。live 結果另記版本與原生 hook 證據；帳號、模型或 trust 不可用時記 blocked，不當 pass。
