# 使用情境報告 — baseline `__suite__` 毒化修復（套件層失敗的重跑確認＋失明警告）  (run_id: 2026-09-06-baseline-suite-guard)

> 本報告自足：不依賴對話上下文。引用檔案以路徑＋行號指向。
> 上游證據：spec/2026-09-06-baseline-suite-guard.md、risk/2026-09-06-baseline-suite-guard.md。
> 本需求無「人類終端使用者」與 UI；「使用者」＝執行 eval-flow 的 agent。情境主軸＝「哪些流程路徑會踩到 baseline／check 的這段行為」。

## 角色

- **主 flow（eval-flow agent）**：唯一會呼叫 `baseline`（第一次 step 5 前建基準）與 `check`（每 sub_task step 5、commit 前全套）的 actor。是 B1／B2 兩條行為變更的直接觸發者。呼叫點：skills/eval-flow/SKILL.md:96、skills/test-strategy/SKILL.md:16／63／106。
- **code-writer（測試自驗 agent）**：只准跑 `mine`（.claude/agents/code-writer.md:38），不碰 `baseline`／`check`。但 `mine` 與 baseline 共用 `_parse_fails()`（test_baseline.py:73-77 → :58-64），整套 argv rc≠0 且無可解析失敗時 `fails` 也會含 `__suite__`。**Spec §4 明列不改 mine**——列為互動點與開放問題，非本次情境。
- **跨 run 沿用機制（系統面）**：`find_reusable_baseline()`（test_baseline.py:121-140）在「同 HEAD 同 cmd」時把先前 run 的 `stable_failures` 沿用給後續 run。它是「毒化跨 run 傳染」的載體，也是 B1 管不到的路徑（B1 只作用實跑路徑）。
- **既有歷史毒化 baseline 檔（向後場景 actor，防禦性）**：repo 內**現無**任何毒化 baseline 檔（主 flow `grep -l '__suite__' run/*.test_baseline.json` 零命中核實）。情境 E 為防禦「本制度上線前產生的歷史檔」與「未來毒化」而保留，非現存實例。Spec §4 明列不回填清理；後續讀到毒化檔的 run 由 B2 警告現形。
- **被副作用影響者——讀警告的使用者**：不主動操作 baseline，但 B1／B2 的 stderr／stdout 警告是寫給人看的「失明現形」訊號。警告若沒被看到＝失明依舊，故警告的可見性（管道／措辭）本身是交付價值的一部分。

## 情境

### A — 主 flow 建 baseline，遇暫時性套件層失敗（B1 核心，happy-fix path）  角色: 主 flow
- 前置: run 進場第一次 step 5 前；無可沿用 baseline（新 HEAD 或帶 `--fresh`），走實跑路徑（test_baseline.py:163）。
- 操作: `python3 .claude/hooks/test_baseline.py baseline` → 第一次全套 rc≠0 且無可解析個別失敗 → `fails == {"__suite__"}` → **重跑一次**；第二次不含 `__suite__`。
- 預期: 以第二次結果為 `stable_failures`（暫時性套件失敗不記錄）；stdout 印一行「套件層非零退出未重現，以重跑結果為準」。
- I/O: input `--cmd`（省略讀 manifest `test_command`）＋ run_id / output `run/<run_id>.test_baseline.json`（`stable_failures` 不含 `__suite__`）/ 副作用：寫 baseline 檔、**多跑一次全套**（成本 ×2，僅此場景）。

### A-edge1 — 首跑 rc≠0 但可解析出個別失敗（不重跑）  角色: 主 flow
- 觸發: 第一次全套 rc≠0，但 FAIL_PATTERNS 抓到 ≥1 個個別失敗 → `fails` 非空且不等於 `{"__suite__"}`。
- 預期: **不重跑**（執行次數 1），照舊單次快照，個別失敗照記為 stable。
- I/O: output baseline 檔含那些個別失敗 / 副作用：寫檔、全套執行次數 = 1（對應 Spec §3 測試案 4）。

### A-edge2 — B1 重跑第二次解析出個別失敗（非 `__suite__`）  角色: 主 flow
- 觸發: 第一次 `fails == {"__suite__"}` 觸發重跑；第二次 rc≠0 且解析出個別失敗（不含 `__suite__`）。
- 預期: 以第二次的個別失敗為 `stable_failures`（第二次是更完整觀測；risk §技術風險第 2 條已裁「正確」）。
- I/O: output baseline 檔含第二次的個別失敗 / 副作用：寫檔、全套執行 2 次。

### B — 主 flow 建 baseline，套件層失敗可重現（環境真壞，照記＋大聲警告）  角色: 主 flow
- 觸發: 實跑路徑，第一次與重跑第二次**皆** `fails == {"__suite__"}`。
- 預期: 照記 `__suite__` 進 `stable_failures`（記錄是事實）；stderr **大聲警告**：baseline 含 `__suite__`、gate 將對全套層級失敗失明、建議修環境後 `--fresh` 重建。
- I/O: output baseline 檔含 `__suite__` / 副作用：寫檔、全套執行 2 次、stderr 警告行（對應 Spec §3 測試案 2）。

### C — 主 flow 沿用既有 baseline，沿用來源含 `__suite__`（B1 管不到）  角色: 主 flow / 跨 run 沿用機制
- 前置: 同 HEAD 同 cmd 存在可沿用 baseline（test_baseline.py:147-162），且該來源的 `stable_failures` 含 `__suite__`。
- 操作: `baseline`（不帶 `--fresh`）→ 命中沿用 → **不實跑、不重跑**，直接寫沿用名單（含 `__suite__`）＋ `reused_from`。
- 預期: B1 **不觸發**（只作用實跑路徑）；毒化沿用發生。失明現形交給下游 check 的 B2。
- I/O: output baseline 檔（`stable_failures` 含 `__suite__`、`reused_from` 指來源 run）/ 副作用：寫檔、stdout 印「沿用 X 的 baseline」。**開放問題 3**：此沿用當下是否也應提示來源含 `__suite__`。

### D — 主 flow 跑 check，baseline 含 `__suite__`（B2 失明警告）  角色: 主 flow
- 前置: baseline 檔 `stable_failures` 含 `__suite__`（來源可為情境 B 照記、情境 C 沿用、或既有歷史檔）。
- 操作: `check`（每 sub_task 或 commit 前全套，test_baseline.py:183）→ 讀入 baseline，`known` 含 `__suite__`。
- 預期: **印一行警告**（本次判定對全套層級失敗失明）；**不改變判定邏輯與 exit code**（無新失敗仍 exit 0）。
- I/O: input baseline 檔＋全套結果 / output 警告行＋原判定 / 副作用：純輸出行（零成本）；`failure_log` 仍照舊僅在真失敗時 append（對應 Spec §3 測試案 3）。

### D-edge1 — check 全套崩潰、`__suite__` 已在 known（靜默失明的原 bug 現象）  角色: 主 flow
- 觸發: baseline `known` 含 `__suite__`，本次 check 全套崩潰使 `fails == {"__suite__"}` → `new = fails - known` 為空（test_baseline.py:195）。
- 預期: 判定 PASS（exit 0）——**這正是原 bug 的失明行為，B2 不改判定**；差別只在現在**同時印 B2 警告**讓失明可見。
- I/O: output exit 0 ＋ B2 警告 / 副作用：無（不 append failure_log）。

### E — 向後場景：既有歷史毒化 baseline 檔  角色: 既有歷史檔 / 主 flow
- 前置: repo 內現無毒化 baseline 檔（主 flow grep 核實，零命中）；本情境防禦「制度上線前遺留」或「未來仍可能產生」的含 `__suite__` 檔——防禦性場景，非現存實例。
- 預期: **不回填清理冷溯源檔**（Spec §4）；後續 run 若沿用毒化檔（情境 C）或對它跑 check（情境 D）→ 由 B2 警告現形。
- I/O: 副作用：無（明示不改歷史檔）。

## 與現有功能互動點

- **`_parse_fails()`（test_baseline.py:58-64）**：sentinel `__suite__` 的來源，**不動**（Spec §4；check 端依賴它抓全套崩潰）。B1 只在其下游對 `fails == {"__suite__"}` 加分支。回歸風險：若誤改此函式會同時影響 baseline／check／mine 三路。
- **`cmd_check` 非確定性重跑（test_baseline.py:197-203）**：既有的 check 端惰性重跑與 B1 的 baseline 重跑是**兩個獨立機制**，勿混用。B2 只在讀 baseline 後加一行警告，不碰此重跑邏輯。回歸風險：B2 新增輸出行可能碰到既有測試對 check 輸出的斷言（risk §業務風險第 2 條，writer 先跑 mine 現形）。
- **`find_reusable_baseline()`（test_baseline.py:121-140）＋沿用寫檔（:147-162）**：B1 明確**不覆蓋**此路徑（情境 C）；毒化沿用只由 B2 在下游 check 現形。
- **`cmd_mine` / `run_tests_argv`（test_baseline.py:73-77、331-354）**：與 baseline 共用 `_parse_fails`，同樣會產 `__suite__`。Spec §4 排除 mine——確認不在本次修（開放問題 4）。
- **文件 `skills/test-strategy/SKILL.md` baseline 節（:13-24）**：B3 需補一句 `__suite__` 重跑確認＋失明警告的行為描述，指向式不重述實作。回歸風險：純文件，無。

## 正確性假設清單（需使用者逐條裁示）

1. **`__suite__` 與個別失敗不共存**：`fails 含 __suite__ ⟺ fails == {"__suite__"}`。消費點 `.claude/hooks/test_baseline.py:62-63`（`_parse_fails` 僅在 `returncode != 0 and not fails` 時 `add("__suite__")`，故先解析出個別失敗則不會再加 sentinel）＋ B1 將新增的判斷式（cmd_baseline :163 附近）。被破壞時可觀察差異：若此性質不成立（某框架能同時輸出可解析失敗且觸發 sentinel），B1 用 `== {"__suite__"}` 會在「有 `__suite__` 但夾帶個別失敗」時漏判、不重跑。**已由現行實作驗證為真需求**。裁示（開放問題 2）：B1 採 `"__suite__" in fails`——即使假設 1 未來失效（sentinel 與個別失敗共存）仍會觸發重跑，對 FAIL_PATTERNS 變動韌性較高。
2. **重跑觀測獨立且第二次更可信**：B1「以第二次結果為準」假設兩次全套執行相互獨立、第二次是更完整觀測。消費點 B1 重跑分支（本 run 新增）。被破壞時可觀察差異：若環境為**雙向 flaky**（第二次也可能偶發假綠或偶發崩潰），單次重跑不足以穩定判別——`stable_failures` 偶爾仍誤含或誤缺 `__suite__`。這是「只重跑一次」的已知殘留風險 → 見開放問題 1（非「疑似非需求」，是需使用者接受殘留機率的裁示）。

## 開放問題（需使用者確認）

1. **B1 重跑次數＝1 是否足夠？**（背景：診斷指出目標專案全套約半數執行出現暫時性非零退出）。預設傾向「一次」（Spec §2 B1 已定，成本 ×2 已是上限、正常路徑零成本）；若改「N 次多數決／重試到穩定」則 B1 實作與測試案 1／2 需改，且最壞成本升為 ×N。若接受一次，殘留風險為：兩次都恰好碰到暫時性崩潰時仍誤記 `__suite__`（此時退回情境 B，由 stderr 警告現形＋建議 `--fresh`）——請確認可接受此殘留由警告兜底。
   - **裁示：重跑 1 次（與 check 惰性重跑對稱；兩次皆崩 → 照記＋B2 警告兜底，接受殘留）（2026-09-06 HITL）**
2. **B1 判斷式採 `fails == {"__suite__"}` 還是 `"__suite__" in fails`？** 預設傾向 `== {"__suite__"}`（依假設 1 的不共存性，Spec §1 明示可簡化）；若改 `in` 則對「假設 1 萬一失效」更防禦、但語義稍寬（有夾帶個別失敗時也會觸發重跑，成本略增）。影響 B1 實作 item 與測試案 4 的邊界斷言。
   - **裁示：採 `'__suite__' in fails`（對未來 FAIL_PATTERNS 變動韌性較高）（2026-09-06 HITL）**
3. **情境 C 沿用毒化 baseline 時，`baseline` 子命令當下是否也印警告？** 預設傾向「不加」（依 Spec，統一交給下游 check 的 B2 覆蓋沿用路徑）；若加則 baseline 沿用路徑（test_baseline.py:158-161 附近）多一行輸出、多一個測試點，好處是毒化在沿用當下就現形、不必等到 check。
   - **裁示：沿用時不另印警告，交給 check 端 B2 兜底——照預設（2026-09-06 HITL）**
4. **code-writer 的 `mine` 路徑同樣會產 `__suite__`（整套 argv 崩潰時 BLOCK 顯示 `__suite__`），是否納入本次修？** 預設傾向「不改」（Spec §4 明列排除 mine，理由：mine 不寫 baseline、不做扣除，`__suite__` 只是當次 BLOCK 顯示而非永久毒化）；若要改則新增 code-writer 面情境與對應 item，擴大範圍。
   - **裁示：不納入本次修（Spec §4 範圍排除維持）（2026-09-06 HITL）**
5. **B1／B2 警告的關鍵字是否需固定文案？**（測試案 2／3 斷言「含失明提示／警告字樣」）。預設傾向「由實作定關鍵字（如含『失明』或『`__suite__`』字樣），測試斷 substring」；若使用者要求固定完整文案，則文案寫進契約表、測試改斷完整字串。影響測試斷言穩定性與日後文案微調自由度。
   - **裁示：警告文案由實作定關鍵字、測試斷 substring——照預設（2026-09-06 HITL）**

Self-check: 已涵蓋 happy-fix（A）＋邊界（A-edge1/2、D-edge1）＋異常（B）＋沿用傳染（C）＋向後（E），每情境有 id、I/O 與副作用，兩條正確性假設與五條開放問題已攤開且未默默假設——待使用者逐條裁示，未回寫 manifest。
