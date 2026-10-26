# 測試套件盤點（2026-10-26）

執行入口：`python3 -m unittest discover -s tests`。修改 Python 腳本時，仍須檢查相容入口及真實子程序路徑。日常變更先跑直接相關的測試；交付時依 Eval Flow 的 test-strategy 選驗證範圍。

## 量測結果

修改前完整執行：800 項，測試本身合計約 102 秒，全部通過。逐項計時後，耗時最高的是 `test_tier1_adaptive`（13 項／17.28 秒）、`test_flow_cli`（26 項／8.88 秒）、`test_test_baseline`（53 項／8.58 秒）、`test_eval_gates`（159 項／7.26 秒）。`test_stats` 有 59 項，但合計約 0.61 秒。這些數字只代表當次機器和來源，不當作效能門檻。

整理後完整執行：781 項，約 93.65 秒，全部通過。兩次量測的環境與來源不同；時間差只作參考。少 19 項的依據：

| 來源 | 少掉的執行 | 理由與保留的驗證 |
|---|---:|---|
| `test_run_verify.py` | 9 | 快取子類原本繼承並重跑父類 9 項；兩組測試改共用 fixture，各案例只執行一次。真實子程序測試仍在父類。 |
| `test_verification_snapshot.py` | 5 | v2 子類原本繼承並重跑 v1 的 5 項；各自測試仍執行。 |
| `test_eval_gates.py` | 1 | `test_verify_passed_false_key_blocks` 與 `test_verify_passed_false_blocks` 方法本文完全相同，保留後者。 |
| `test_evals_suite.py` | 4 | 移除常數原文字面檢查、程式行序檢查、固定至少三案例的數量檢查及 runner 文字包含檢查。保留 CLI dry-run 實際輸出、假 CLI 未被呼叫、案例非空、fixture 真實安裝與規則指紋檢查。 |

`test_dispatch.py` 原有自訂 `load_tests`，只為阻止子類重跑父類測試。現改為共用 fixture，移除特殊載入器；原有 30 個案例維持。這減少了測試新增時意外被載入器漏掉的風險。

本次對修改的 Python 測試檔執行 Black，會造成較多排版差異。以 AST 核對方法本文：`test_dispatch.py` 的 30 項、`test_run_verify.py` 的 20 項、`test_verification_snapshot.py` 的 9 項均未改變；`test_eval_gates.py` 只刪一項精確重複；`test_evals_suite.py` 只刪上述四項並調整三項既有方法（dry-run、案例非空、Claude skill 路徑斷言）。格式差異不作為刪除測試的理由。

## 後續判斷準則

測試數量本身不表示品質或成本。先找同一斷言的精確重複、繼承重跑，以及只檢查程式文字的案例；再核對保留測試能否抓到相同錯誤。舊版相容、hook 阻擋、實際 Git 提交及子程序路徑是不同契約，不能只因名稱相近就合併。若要繼續縮短時間，先量測慢的整合測試，確認是否有相同路徑重跑，再改 fixture 或共用準備工作。
