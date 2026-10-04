# 循環 step 1–2：實作與 staging

1. 依「派工機制」節派工 `code-writer` subagent 產出程式碼
   - **批次派工（省 spawn 稅）**：派工單位＝**task**，同 task 多 item 一次派給同一 code-writer（知識前置一次組裝、item 間共用 context）。條件：①批內合計預估 ≤400 行（與合併審查上限對齊，超過拆批）②`[P]` item 不混批（保留平行／worktree 路徑）③**失敗隔離**：單 item 帶失敗交付只退該 item，其餘 item 照常收④工作報告與憑據**逐 item 分節**（審查輪輸入不變、逐 item 核對，格式住 code-writer.md）。單 item 的 task 照舊
   - **知識前置（硬性步驟）**：呼叫前，主 flow 把三個來源的相關內容**原文貼進 writer prompt 的硬性約束區**——不是叫 writer「自己去讀」，知識只有以明文約束前置進 prompt 才有效（R-011）。三源：
     - **retro 條目**：先以本 item `files` 的模組路徑 grep `retro/RETRO.md` 的標籤篩選（標籤第一段＝模組路徑，見 retro agent 規範），主 flow 再補判同類操作／同類風險面的條目
       - **篩選由 script 執行**：`python3 .agent-flow/scripts/retro_select.py --files <該 item 的 files>`——它一次做完下兩條（排除 retired、錨點鮮度檢查），輸出可直接貼進硬約束區的條目原文與 retire 候選清單。機械步驟不留給模型逐次手做；主 flow 仍須就輸出補判同類操作／同類風險面的條目
       - **排除 retired 條目**：grep 命中標 `［retired ...］` 的條目一律不選（標記定義住 RETRO.md 檔頭，單一枚舉點——此處指向式引用、不重列格式）
       - **貼入前鮮度檢查**：選中的每條若帶前提錨點 `［錨點: X］`，貼進 prompt **前**先 grep 該錨點（檔案／helper／機制名）是否仍存在於 codebase——**不存在→不貼該條**，改列入「retire 候選」於收尾回報使用者（比照 memory 規則「recalled 條目須先驗證仍存在」）。錨點失效的舊約束是對已消失機制的錯誤指令，貼進去只會與新功能打架
     - **模組 conventions**：本 item 觸及模組的子目錄 `AGENTS.md` 與目前 harness 入口（存在則摘錄相關段）
     - **impact report 慣例段**：本 run 曾具名問題觸發 `impact-analyzer` 且答案含該模組時，摘錄「各模組既有慣例」與「可重用既有元件」節（節名見 impact-analyzer 定義；答案寫在 Spec）
     - grep 篩選的對象是**模組名片段**（取自 files 路徑的目錄／檔名，如 `eval_gates`、`hooks`），不是整段路徑——retro 標籤慣用全形 `／`，整段半形路徑會靜默零命中
     - 三源皆無相關內容時在 prompt 註明「知識前置：三源均無相關內容」（留痕，防跳步）
     - **retro 約束 vs Spec 衝突仲裁**：**衝突成立判準（先驗）**——僅題材重疊／同域**不算**衝突；成立須同時①指認兩邊對撞的**條文原句**（R-NNN 約束句 vs Spec／DoD／契約 row 原文）②寫出**具體後果**（照約束做會違反 Spec 哪一句、產生什麼可觀察的錯誤行為）——寫不出後果＝不是衝突，不記仲裁、兩者照常都守。判準成立時：前置的 retro 約束與本 item 的 Spec／DoD／契約表衝突（新功能有正當理由要做某條約束禁止的事）→ **Spec 優先**，但 writer 與主 flow **不可靜默選邊**：須在交付報告寫仲裁記錄（衝突的 R-NNN、衝突點一句、採用哪邊、理由一句，比照契約仲裁記錄格式）。主 flow 收到後判「該約束前提已變、列 retire 候選」或「Spec 該收緊」——沉默採一邊會讓過期約束無限存活或讓 Spec 悄悄違反硬規則
   - **測試管轄註記**：派工 prompt 附一句「測試自驗只准跑 `python3 .agent-flow/scripts/test_baseline.py mine`，依你定義中的測試管轄規則」（**不傳 `--strike-key`**——該旗標只有 `check` 消費）（writer 層 mine 模式細節住 test-strategy skill，不重述）
     - `[P]` item 在 fan-out（各開 worktree）或循序退回下 mine 模式均適用——隔離樹或逐個執行時未提交變更範圍可正確推導
   - **契約前置與仲裁句（硬性）**：派工 prompt 必須把本 item 的**行為契約表原文**（task 檔的 `契約:` 行，含邊界 row，及 `退場:` 行——writer 須在同一 run 刪除其列出的測試，格式住 task-decomposition skill）貼進硬約束區作為仲裁基準——不是叫 writer 自己翻 task 檔（與知識前置同一教訓，R-011）。
     - 並附一句：「測試紅時先仲裁再動手，對到契約表 row 判哪邊錯；**契約表沒答案 → 帶失敗交付是正確行為，硬湊綠燈才是違規**」
     - 無契約表的 item（Tier 1 無表 fallback）仲裁句改指 DoD
     - writer 以「表沒答案」帶失敗交付時，**主 flow 裁決**：讀 Spec／usage 報告判該行為的預期，把裁決結果補進契約表（表可增補、single source 不變）再回派；Spec 本身有洞才走升級逃生門問使用者
   - **交付稽核（writer 交付時）**——正常交付（記錄對得上）瞄一眼即過，不展開：核對工作報告的「仲裁記錄」——紅過的測試每條都要有仲裁行，判「測試超出契約」者核對 row 引文與 task 檔原文一致（對不上＝假仲裁，退件）。writer 的 mine 模式測試自驗不落檔、不跨對照；改測試湊綠由 checker 核對「契約 row 逐條有對應測試斷言」時現形
修正重審與驗證重用依 `SKILL.md「效率與驗證重用」`：首輪完整獨立審；僅已審版本到目前 index 的有效 delta 可縮小重審，契約與未解問題仍完整提供。

2. 將變更檔案 `git add` 進 staging area（確保 checker／code-reviewer 可透過 `git diff --cached` 讀取）。
   - **預設派 task-verifier（checker）時，prompt 附 `git diff --cached --stat -- <files>` 輸出**（僅檔名與行數統計，checker 不讀 diff 內容）
   - **升級為 code-reviewer 全 diff 審時，prompt 硬性指示改用 `git diff --cached -- <files>`**（file-scoped 完整 diff）
   - `<files>`＝**當前 sub_task（task）的 `files`**（主 flow 讀 `eval_state.json` 該 sub_task 的 `files` 欄帶入，即該 task 全部 item 的聯集；收斂到當前 task 涉及檔，避免跨 sub_task staging 累積污染）。
     - **注意**：`eval_state.py list-files` 是全 sub_task 聯集，不是單一 sub_task 來源、不可用於此。此收斂為退回主 worktree 循序時的污染修法（與 fan-out 無關、底層必需）。
   - 審查以 task 為界，staging 天然以 task 分批，不另做批前快照
