# 影響面報告 — baseline `__suite__` 毒化修復（run_id: 2026-09-06-baseline-suite-guard）

> 本報告自足：不依賴對話上下文。所有證據以 `檔案:行號` 指向，接手者讀檔即可驗證。
> 上游：spec/2026-09-06-baseline-suite-guard.md、usage/2026-09-06-baseline-suite-guard.md、risk/2026-09-06-baseline-suite-guard.md。
> 改動標的（範圍提示）：`.claude/hooks/test_baseline.py` 的 `cmd_baseline`（B1 重跑確認）＋ `cmd_check`（B2 失明警告）＋ `skills/test-strategy/SKILL.md` 一句文件同步。

## 1. 觸及模組清單

- `.claude/hooks/test_baseline.py` — B1 改 `cmd_baseline`（:143-181，實跑路徑加 `__suite__` 重跑分支）、B2 改 `cmd_check`（:183-220，讀 baseline 後加失明警告行）。
- `tests/test_test_baseline.py` — Spec §3 四條測試案（B1 重跑三態＋B2 警告）補入，沿該檔既有慣例（單元測 + subprocess 整合測）。
- `skills/test-strategy/SKILL.md` — B3 文件同步，於 Baseline 節（:13-24）補一句 `__suite__` 重跑確認＋失明警告的指向式描述。

不觸及（明列排除，避免拆分者誤納）：`_parse_fails`（:58-64，sentinel 來源，Spec §4 不動）、`cmd_mine`／`run_tests_argv`（:73-77、:331-354，Spec §4 排除 mine）、`find_reusable_baseline`／沿用寫檔（:121-140、:147-162，B1 不覆蓋沿用路徑，見第 5 節）、`.claude/hooks/eval_gates.py`／`.claude/hooks/stats.py`（僅間接消費 baseline 檔，見第 4 節，本次不改）。

## 2. 各模組既有慣例

### `.claude/hooks/test_baseline.py`

- **輸出慣例（B1／B2 警告行的直接對照範本）**：所有面向使用者的行統一帶 `[test-gate]` 前綴。正常／通過訊息走 `print(...)`（stdout）：baseline 寫入摘要 `.claude/hooks/test_baseline.py:175-178`、既有壞測試清單 `:179-180`、沿用訊息 `:158-161`、check PASS `:217-220`、check 重跑提示 `:198`。**阻擋／警示走 stderr**：`fail()` helper `:53-55`（`print(..., file=sys.stderr)` + `sys.exit`）、check BLOCK `:211-213`（`file=sys.stderr`）。非確定性放行走 stdout `:203`。→ B1「未重現以重跑為準」屬資訊性走 stdout（Spec §2 B1 明寫 stdout）；B1「兩次皆崩大聲警告」與 B2 失明警告依 Spec 走 stderr／「印一行」，拆分者須依 Spec §2 定管道，測試斷言用 substring（開放問題 5 裁示：關鍵字由實作定、測試斷 substring）。
- **命名慣例**：子命令進入點 `cmd_<verb>`（`cmd_baseline` :143、`cmd_check` :183、`cmd_mine` :331、`cmd_related` :357）；私有 helper 底線前綴（`_parse_fails` :58、`_save` :223、`_append_mine_log` :298）；失敗集合變數統一名 `fails`（:70、:77、:163、:194），退出碼常數化在 docstring `:24`（exit 0/2/1）。
- **baseline 檔寫入慣例（B1 落點）**：`cmd_baseline` 實跑路徑用**內聯** `json.dump(..., indent=2, ensure_ascii=False)` + `f.write("\n")` 寫檔（:172-174），與 helper `_save()`（:223-226）語義相同但**未共用**——沿用路徑（:151）與 `cmd_check` 的 failure_log append（:210）走 `_save`。B1 在實跑路徑加重跑分支後仍寫同一 `data` dict（:166-171），`stable_failures` 恆 `sorted(...)`（:170）。拆分者注意：B1 要在 `fails, _ = run_tests(cmd)`（:163）與寫檔（:166）之間插重跑分支，勿破壞 `sorted` 與內聯寫檔慣例。
- **`__suite__` 判斷式慣例**：sentinel 只在 `_parse_fails` 的 `returncode != 0 and not fails` 時加入（:62-63）。開放問題 2 裁示 B1 用 `"__suite__" in fails`（非 `== {"__suite__"}`），對未來 FAIL_PATTERNS 變動韌性較高（usage:78）。
- **錯誤處理慣例**：檔案讀取一律 `try/except (OSError, json.JSONDecodeError)` 後退到 None／預設（:86、:104、:117、:136），不讓例外冒泡；使用錯誤走 `fail(msg)` exit 1（:89、:107、:187）。

### `tests/test_test_baseline.py`（測試慣例——B1／B2 新測試案落點）

- **框架**：`unittest`，`python3 -m unittest discover -s tests`（檔頭 :4；亦即 manifest `test_command`）。
- **隔離 run 目錄慣例（範圍提示重點）**：每個 TestCase 的 `setUp` 建 `tempfile.TemporaryDirectory()` 存 `self.dir`，寫入 `eval_state.json`（`{"run_id": "t"}`），`tearDown` 呼 `self.tmp.cleanup()`（`:38-44`、:245-257、:389-399、:468-479）。所有 script 呼叫經 `run_script(*args)` 以 `cwd=self.dir` 隔離（`:46-50`），baseline 檔固定讀 `self.dir/run/t.test_baseline.json`（`read_baseline` :52-53、:356-357）。→ B1／B2 新測試案沿用 `BaselineScriptTest`（:37）的 `setUp`／`run_script`／`read_baseline`／`build_baseline`（:55-58）。
- **stub 測試指令慣例（範圍提示重點）**：以 shell 字串當假 `--cmd` 注入受控 rc 與輸出。範本：`CMD_STABLE` 印 `FAILED ...; exit 1`（:21-23，rc≠0 且可解析 → 對應 A-edge1「不重跑」）；`CMD_NEW_FAILURE`（:24-27）；**非確定性用計數檔 `m` 控制「第一次 vs 重跑」不同結果** `CMD_NEW_NONREPRODUCIBLE`（:28-34，`m=$(cat m ...); m=$((m+1)); echo $m > m; [ $m -eq 1 ] && ...`）——這正是 B1「首跑崩、重跑不崩」測試案 1／A 情境要複用的 stub 模式：首跑 `exit 1` 無可解析失敗（→ `__suite__`）、重跑 `exit 0`。B1 測試案 2（兩次皆崩）＝固定 `exit 1` 無可解析輸出；A-edge2（重跑解析出個別失敗）＝首跑無可解析、重跑印 `FAILED ...`。
- **沿用側效檔慣例**：`CMD_TOUCH = 'touch ran; exit 0'`（:141）＋斷言 `(self.dir/"ran").exists()` 判斷「是否真的重跑了測試」（:149、:161、:169、:177）——B1 測試若需斷言「重跑執行了幾次全套」可借此模式（如用計數檔統計呼叫次數）。
- **既有 baseline 檔注入慣例**：`write_prev_baseline`（:130-138）與 `MineSubcommandTest.write_baseline`（:266-274）手寫 baseline JSON dict。→ B2 測試案 3（baseline 含 `__suite__` → check 印警告、exit 不變）可仿此直接寫一個 `stable_failures: ["__suite__"]` 的 baseline 檔再跑 check。
- **git repo fixture 慣例**：需 HEAD／沿用的測試用 `init_git`（:118-128）先 `git init` + `--allow-empty` commit 取 HEAD——B1／B2 核心測試不涉沿用可不建 git（`BaselineScriptTest` 多數案例即無 git）。
- **斷言慣例**：`assertEqual(result.returncode, N, result.stderr)`（第三參回帶 stderr 便於除錯，:57、:69）；輸出斷言用 `assertIn(substring, result.stdout/stderr)`（:70、:76、:92）——B1／B2 警告依開放問題 5 裁示斷 substring（非固定完整文案）。

### `skills/test-strategy/SKILL.md`

- **文件慣例**：Baseline 節在 `## Baseline（...）`（:13）下以 bullet 描述行為，指令置 code fence（:15-17）。真實失敗來源規則標 `（R-NNN）`（檔頭 :11）。B3 屬純文件、指向式（不重述實作），落點在 :20-22 附近（現述「跑一次，所有失敗記為 stable_failures」處補「`__suite__` 套件層失敗重跑確認＋check 端失明警告」一句）。

## 3. 可重用既有元件

- `.claude/hooks/test_baseline.py:67` `run_tests(cmd)` — B1 重跑第二次全套直接複用（回 `(fails, returncode)`，與首跑同函式，保證解析一致）。
- `.claude/hooks/test_baseline.py:58` `_parse_fails(out, returncode)` — 由 `run_tests` 內部呼叫，B1 不需直接動它，但重跑結果的 `__suite__` 判定即出自此（:62-63），是 B1 判斷式 `"__suite__" in fails` 的語義來源。
- `.claude/hooks/test_baseline.py:53` `fail(msg, code=1)` — 標準錯誤退出 helper（stderr + exit）；B2/B1 若需硬錯可用，但本次警告不改 exit（見第 5 節），故多半只借其 stderr 輸出樣式，不呼叫本函式。
- `.claude/hooks/test_baseline.py:223` `_save(path, data)` — 統一 JSON 寫檔 helper（indent=2、ensure_ascii=False、尾換行）；B1 實跑路徑目前為內聯寫檔（:172-174），拆分者可選擇維持內聯（surgical，符合既有該路徑寫法）或收斂到 `_save`（勿為此擴大 diff）。
- `tests/test_test_baseline.py:55` `build_baseline()`、`:46` `run_script()`、`:52` `read_baseline()`、`:141` `CMD_TOUCH`、`:28-34` 計數檔 stub 模式 — B1／B2 測試案直接複用的既有測試 helper／範本（見第 2 節測試慣例）。

## 4. 被改介面的呼叫端清單

被改的是 `cmd_baseline`／`cmd_check` 兩個子命令的**行為**（非簽章——皆 `(args)` 且經 argparse 分派，:398、:404），呼叫端分兩類：(A) 觸發子命令的流程文件與 agent；(B) 消費其產物 `run/<run_id>.test_baseline.json` 的其他程式。

### 介面一：`baseline` 子命令（B1 改其實跑路徑行為）

- `skills/test-strategy/SKILL.md:16` — 文件示範呼叫 `test_baseline.py baseline`（Baseline 節）；B3 同檔補述。
- `skills/eval-flow/SKILL.md:96` — step 5 描述「baseline 於第一次 step 5 前建立單次快照」（行為描述，B1 改為 `__suite__` 場景多跑一次；此句「單次快照」對個別失敗仍成立，拆分者評估是否需微調用語——Spec §2 未要求改此檔，B3 只點 test-strategy）。
- `skills/parallel-run/SKILL.md:58` — 批次層 baseline 手動帶 `--cmd` 呼叫；B1 邏輯同樣作用於此路徑（無 manifest 但走實跑），行為變更一致適用，無需改文件。
- **查詢方法**：`grep -rn "test_baseline.py baseline\|\.py baseline" --include=*.md --include=*.py --include=*.sh .` → 命中 test-strategy:16、eval-flow:96（描述句）、parallel-run:58、test_baseline.py:5（us？docstring）；`grep -rn "cmd_baseline\|set_defaults(func=cmd_baseline)" .` → 僅 test_baseline.py:143、:398（定義＋argparse 綁定），無其他 Python 直呼。

### 介面二：`check` 子命令（B2 加失明警告，不改判定／exit）

- `skills/test-strategy/SKILL.md:63`（sub_task 相關測試 check）、`:106`（收尾全套 check `--strike-key full_suite`）— 文件示範呼叫。
- `skills/eval-flow/SKILL.md:96`（step 5 gate 判定以 check 為準）、`:103`（step 6 ⓪收尾全套 check `--cmd ... --strike-key full_suite`）— 流程呼叫點。B2 只多印一行、不改 exit code，這些 gate 語義不受影響。
- `skills/parallel-run/SKILL.md:58`（merge 後全套 check，判準「無新增失敗」）— B2 警告若 merge baseline 含 `__suite__` 會現形，行為相容。
- **查詢方法**：`grep -rn "\.py check\|cmd_check" --include=*.md --include=*.py --include=*.sh .` → 命中 test-strategy:63/:106、eval-flow:96/:103、parallel-run、test_baseline.py:6（docstring）、:183/:404（定義＋綁定）；無其他 Python 直呼 `cmd_check`。

### 介面三：baseline 檔產物 `run/<run_id>.test_baseline.json` 的內容消費端

- `.claude/hooks/test_baseline.py:190` `cmd_check` — `known = set(base.get("stable_failures", []))`，`new = fails - known`（:195）。**B1 讓暫時性 `__suite__` 不再進 `stable_failures`；B2 在此讀入後加警告**。這是本次自我消費端。
- `.claude/hooks/test_baseline.py:138`、`:156` `find_reusable_baseline`／沿用寫檔 — 讀來源 run 的 `stable_failures` 沿用（含 `__suite__` 會傳染，即情境 C）。B1 不覆蓋此路徑（Spec §2、usage 情境 C），毒化沿用交由下游 check 的 B2 現形。
- `.claude/hooks/stats.py:203-207` — `load(...test_baseline.json)` 後取 `len(base.get("stable_failures", []))` 記入 baseline 欠帳走勢（`stats.py:16` 定義）。**只讀長度、不讀內容值**：B1 讓暫時性 `__suite__` 不再計入 → baseline 欠帳數走勢更真實（正向副作用，非破壞）；不需改 stats.py。測試 `tests/test_stats.py:53`（寫 `.test_baseline.json`）、`:88` `test_baseline_trend` 是既有覆蓋。
- `.claude/hooks/eval_gates.py:43` `MANIFEST_RE` — **只用檔名 pattern 排除 `.test_baseline.json`（負向後查），從不讀其內容**（grep 確認 eval_gates.py 內無 `stable_failures`／`__suite__` 引用）。B1／B2 不影響 eval_gates。測試 `tests/test_eval_gates.py:154`（`test_ignores_test_baseline`）、:845（刪除放行）是既有覆蓋，不受影響。
- **查詢方法**：`grep -rn "stable_failures" --include=*.py .` → 命中 test_baseline.py:156/:170/:190（＋docstring :16/:18）、stats.py:206；tests 側 test_test_baseline.py 多處斷言、test_stats.py:53。`grep -rn "test_baseline\|__suite__" .claude/hooks/eval_gates.py` → 僅 :20/:31/:43 註解與 pattern，**無內容讀取**。`grep -rln "\.test_baseline\.json" run/ | head` 與 `grep -l '__suite__' run/*.test_baseline.json` → 目前 repo 內無任何毒化 baseline 檔（usage:12、:56 主 flow 已核實零命中；情境 E 為防禦性）。

## 5. 跨模組風險點

- **B2 新增輸出行碰撞既有 check 輸出斷言** — `cmd_check` 現有 PASS 行 `tests/test_test_baseline.py:70`（`assertIn("PASS", ...)`）、BLOCK 斷言 `:76-77`、非確定性 `:92`。B2 多印一行只在 `known` 含 `__suite__` 時觸發，既有測試的 baseline 皆不含 `__suite__`（`CMD_STABLE` 產出的是個別失敗 :62），理應不衝突。**建議確認方式**：writer 先跑 `mine`（risk 業務風險#2）＋新增 B2 測試案 3 前後跑全套 `python3 -m unittest discover -s tests` 確認既有 check 測試不因新行受污染。
- **B1 重跑分支破壞 A-edge1「不重跑」不變量** — 開放問題 2 裁示用 `"__suite__" in fails`：若首跑已解析出個別失敗（`fails` 非空且不含 `__suite__`）不得重跑（執行次數必須 =1，Spec §3 測試案 4／usage A-edge1）。**建議確認方式**：測試案 4 用側效計數（仿 `CMD_TOUCH`／計數檔 `m` 模式）斷言全套只執行 1 次。
- **B1／B2 兩重跑機制混淆** — `cmd_baseline` 的 B1 重跑（新增）與 `cmd_check` 既有惰性重跑（:197-203）是**兩個獨立機制**（usage 互動點）。B1 只作用 baseline 實跑路徑、B2 只在 check 讀 baseline 後加警告、不碰既有 check 重跑。**建議確認方式**：diff 檢查 B1 改動收斂在 `cmd_baseline` :163-171 附近、B2 收斂在 `cmd_check` :190 讀入後的一行，兩者互不越界。
- **沿用路徑毒化跨 run 傳染（B1 覆蓋不到）** — `find_reusable_baseline`（:121-140）把含 `__suite__` 的舊 baseline 沿用給同 HEAD 後續 run（情境 C）。B1 不管沿用，唯一兜底是 B2 在下游 check 現形。**建議確認方式**：確認 B2 對「沿用來的 baseline 含 `__suite__`」與「歷史檔含 `__suite__`」兩路都印警告（Spec §2 B2 明文覆蓋兩路），測試案 3 直接寫毒化 baseline 檔驗證即涵蓋。
- **`_parse_fails` 誤改的三路連鎖** — `_parse_fails`（:58-64）同時被 baseline／check（`run_tests` :70）與 mine（`run_tests_argv` :77）呼叫。Spec §4 明列不動它；若 B1 為判斷 `__suite__` 誤改此函式，會同時影響三路（usage 互動點）。**建議確認方式**：B1 判斷式建在 `cmd_baseline` 內對 `run_tests` 回傳的 `fails` 判斷，**不進 `_parse_fails`**；review 時確認 `_parse_fails` diff 為零。
- **文件與實作漂移（B3）** — test-strategy skill Baseline 節與 eval-flow:96「單次快照」描述可能與 B1 新行為對不齊。**建議確認方式**：B3 補述後確認 test-strategy 的 `__suite__` 行為描述與實作一致；eval-flow:96「單次快照」對個別失敗仍成立，如拆分者判定需同步再納入 B3 範圍（Spec §2 B3 目前僅要求改 test-strategy）。

Self-check: 五節皆填，呼叫端經 grep 全掃並附查詢 pattern（子命令觸發端＋baseline 檔三個內容消費端 stats／find_reusable／check，確認 eval_gates 只用檔名 pattern 不讀內容），測試「隔離 run 目錄＋stub 測試指令」慣例已附行號範本供 B1／B2 複用。
