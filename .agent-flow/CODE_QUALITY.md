<!-- agent-workspace managed -->
# 產碼品質：格式、可閱讀性與 log

本文件是三項規則的共用來源。適用本次新增或修改的程式碼；主 flow 直寫也適用。專案已明定的 formatter、logging 套件及輸出契約優先，派工時寫明採用設定與差異。歷史整理另列 task。

## 格式

- Python 無既定 formatter 時使用 Black；預設資源在 `.agents/skills/eval-flow/assets/black.toml` 與 `requirements-format.txt`。固定版本、88 字元行寬，不啟用 preview。其他語言使用專案既有 formatter。
- 依專案開發環境安装固定依賴；格式化及檢查使用同一個直譯器、版本與設定。保留專案已選定的 formatter，不為導入模板覆寫根目錄設定。
- 對本次新增／修改且仍存在的 Python 檔案明列路徑，先格式化，再執行 `--check`。包含測試檔；不以 `.` 掃整個歷史庫、不用 `--line-ranges` 當作整檔驗收。移除檔案不傳給 formatter。
- Black 會重排整檔；若造成超出 task 範圍的大量變更，先調整 task 範圍與審查計畫，不靜默省略檔案。生成檔先改來源，再重新生成。
- 交付附版本、設定路徑、受檢檔案、命令及退出碼。沒有適用檔案時記「不適用」及原因。工具缺失或檢查失敗時修復後再驗，不記通過。

無專案設定時的命令（`python3` 換成專案直譯器，檔名換成 task 的實際檔案）：

```sh
python3 -m pip install -r .agents/skills/eval-flow/assets/requirements-format.txt
python3 -m black --config .agents/skills/eval-flow/assets/black.toml src/example.py
python3 -m black --config .agents/skills/eval-flow/assets/black.toml --check src/example.py
```

## 可閱讀性

- 名稱說明用途；在上下文不足時避免 `data`、`tmp` 等泛稱。
- 函式有一個明確責任。解析、業務判斷與 I/O 混合且難以追蹤時拆開；純規則維持無 I/O。
- 複雜條件以有意義的名稱表達；使用提前回傳降低巢狀。避免多層三元運算或為縮行而串接副作用。
- 註解說明原因、限制與不變量。formatter 通過不代表結構清楚；reviewer 依變更上下文判斷，不以函式行數作唯一門檻。

### 結構判斷（沿用既有審查）

- 本次變更有複雜分支時，確認各分支的用途與既有行為證據；只有具體缺口才依 test-strategy 補驗，不只為縮短函式拆出單次使用的 helper。
- 相似程式先判斷是否代表同一個決策。必須同步變更的規則優先收斂到單一來源；僅寫法相似、變更理由不同時，不強制共用。
- 本節是結構判斷指引，不引入 CRAP、重複度或 mutation 工具、固定分數門檻或必跑掃描。審查限本次變更及直接相關上下文，歷史整理另列 task。

## Log 分級

按操作結果與影響分級；例外類別本身不能決定 level。

| Level | 條件 | 例子 |
|---|---|---|
| DEBUG | 排查問題才需要的細節 | 分支選擇、快取未命中原因 |
| INFO | 正常的重要狀態變化 | 派工開始、驗證完成、預期 gate 阻擋 |
| WARNING | 異常已恢復或可重試，仍可依契約完成 | 重試已排定、選用統計寫入失敗 |
| ERROR | 本次操作無法依契約完成 | 重試用盡、必要驗收證據寫入失敗 |
| CRITICAL | 整個程序或服務不能繼續 | 必要執行環境失效且必須停止 |

預期 gate 阻擋記 `outcome=blocked` 與穩定 `reason` 碼；若 gate 執行本身失敗，依影響分級。level 不取代退出碼或業務結果。

## Log 內容與輸出

- 每筆包含 UTC `timestamp`、`level`、`logger`、穩定 `event` 與簡短 `message`。事件以 `dispatch.retry_scheduled` 等固定名稱識別；可變資料放欄位，工具不解析 message 文字。
- 依情境加入 `run_id`／`request_id`、`role`、`outcome`、`reason`、`attempt`、`max_attempts`、`duration_ms`、`exit_code`。缺少上下文時省略欄位，不捏造識別碼；不要拿任意欄位覆寫 logger 的保留欄位。
- Python 預設使用標準 `logging`，各模組用 `logging.getLogger(__name__)`。應用入口統一設定 handler、level 與格式；模組 import 時不設定 root logger，純規則由呼叫端記錄結果。
- 新 CLI 診斷預設 INFO，提供 `--log-level` 與 `--log-format text|json`。text 便於閱讀，JSON 每行一筆、保留結構欄位。既有 CLI 新增選項或改格式前，先核對其消費端。
- 命令結果寫 stdout，診斷寫 stderr。JSON 結果及 hook 協定不能混入診斷文字。保留既有退出碼契約。
- 同一失敗由負責處理結果的邊界記錄一次；內層補充錯誤上下文後拋出。未預期例外在該邊界附 traceback；預期輸入錯誤用簡短原因。重試每次記 attempt，最終失敗只記一次 ERROR。
- 欄位採必要資料清單；不輸出密鑰、token、完整 prompt、請求內容或整包環境變數。例外訊息與 traceback 也要檢查並遮蔽敏感值。
- log level 只控制診斷。manifest、必要驗收證據及審計資料按原契約保存，不可改為會被過濾的 log；旁路紀錄失敗是否影響操作，沿用該紀錄的既定契約。

## 交付與驗證

涉及新增／修改 log 或錯誤處理時，writer 列「情境 → event／level → 必要欄位 → 憑據」。覆蓋正常、重試（存在時）、最終失敗；不適用者寫原因，不為湊情境新增重試。

測試或實跑應核對：level 與結果一致、欄位可定位操作、同一失敗不重複、stdout 協定保持、敏感值未輸出；有 level 切換時核對診斷篩選不影響必要證據。斷言 event、level、欄位與可觀察結果，避免鎖住完整訊息文字。沿用既有測試與契約預算，不為每條文案另建案例。

writer 附格式檢查及適用 log 證據；主 flow 在 step 5 核對並將實際命令納入驗證紀錄。checker 核對憑據，reviewer 審查可閱讀性與 log 語意。這些是交付與審查要求；現有 Git hook 不會另行執行 Black 或自動判斷 log 語意。

參考：[Black code style](https://black.readthedocs.io/en/stable/the_black_code_style/current_style.html)、[Python Logging HOWTO](https://docs.python.org/3/howto/logging.html)。
