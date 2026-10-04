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
| tier1-hitl-stop | 計畫確認前不改實作檔、不提交 |
| resume-interrupted | 從 task 2 reviewing 定位，不重跑已 passed 的 task 1 |

CLI smoke 用 harness_smoke.py；它量客戶端整合，與完整 skill 行為評測分開。預設預覽；--live 呼叫模型，--trust-local-hooks 僅批准這次由 runner 產生的暫存 Codex hooks。

```sh
python3 .agent-flow/scripts/harness_smoke.py
python3 .agent-flow/scripts/harness_smoke.py --live --trust-local-hooks --timeout 90
python3 -m unittest tests.test_harness_adapter tests.test_harness_flow tests.test_install_transaction tests.test_harness_smoke
```

本地測試不呼叫付費模型，覆蓋安裝、事件轉換、阻擋、失敗處理與恢復。live 結果另記版本與原生 hook 證據；帳號、模型或 trust 不可用時記 blocked，不當 pass。
