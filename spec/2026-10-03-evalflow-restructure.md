# Spec — eval-flow SKILL.md 結構重組（階段 3）

Run-Id: `2026-10-03-evalflow-restructure`　Tier: 2　manifest: `run/2026-10-03-evalflow-restructure.json`

## §1 背景與需求來源

使用者依 Anthropic「Skill authoring best practices」（https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices）核准了一份五階段 prompt 優化計畫。階段 1、2、4 已於 2026-10-03 以三個 Tier 1 run 完成（commit `ca03eca`、`7f9ddb0`、`59d1359`、`2838eca`：去歷史化、description 瘦身、prose lint 防線）。

**本 run 是階段 3**：`skills/eval-flow/SKILL.md` 的結構重組。原計畫的三項主張：

1. 本體按 tier 重排，Tier 1 路徑前移（依據：Tier 1 佔 54/61 個 run，但其路徑排在檔尾第 209 行）
2. Tier 2 前置（前置 0、具名問題觸發、前置 1、HITL gate）外移到 `references/tier2-prep.md`
3. 循環步驟 1 與 3 加可複製 checklist（官方「Use workflows for complex tasks」：複雜流程給可複製清單供逐步打勾）

本 run 判 Tier 2 的理由碼：**未決重大決策**（分檔邊界與 checklist 形式皆為開放設計空間，見 §4）。

## §2 量測（2026-10-03，commit `2838eca` 的檔案狀態）

`skills/eval-flow/SKILL.md` 共 256 行、25,384 字元。逐節字元數與佔比：

| 節 | 字元 | 佔比 | 哪個 tier 需要 |
|---|---|---|---|
| frontmatter＋檔頭 | 629 | 2% | 全部 |
| Tier 2 完整路徑（節標題＋導語） | 124 | 0% | Tier 2 |
| 前置 0：初始化 | 926 | 3% | Tier 2 |
| 具名問題觸發 | 717 | 2% | Tier 2 |
| 前置 1：分拆 task | 563 | 2% | Tier 2 |
| HITL gate | 290 | 1% | Tier 2 |
| **循環（步驟 1–7）** | **12,018** | **47%** | **全部** |
| 派工機制 | 1,782 | 7% | 全部 |
| Model 指派原則 | 435 | 1% | 全部 |
| Subagent 呼叫原則 | 1,049 | 4% | 全部 |
| 主 flow 憑據紀律 | 1,021 | 4% | 全部 |
| 資料格式與操作規則（指向） | 502 | 1% | 全部 |
| Gate 的硬性執行（指向） | 199 | 0% | 全部 |
| 中斷恢復（指向） | 348 | 1% | 全部 |
| **Tier 1 精簡路徑** | **4,187** | **16%** | **Tier 1** |
| Tier B／Hotfix／併發／fan-out（4 個指向節） | 594 | 2% | 各自路徑 |

**對原計畫主張 2 的修正**：Tier 2 前置四節合計 2,620 字元＝全檔 10%。外移只為 Tier 1 省 10%，而非原計畫假想的大幅瘦身——真正的體積在循環節（47%），且兩個 tier 都需要它。本 Spec 因此把「是否外移」降為開放問題（§4 Q1），並明列三個方案的成本效益。

**循環節不列入外移候選（已評估否決）**：循環節含全部硬性 gate（引文核實二分處置 R-012、🔴 重裁、四類升級觸發、step 5 測試 gate、step 6 收尾順序）。外移它＝把硬 gate 移出主載入路徑，違反 R-002（規則須在執行者的載入路徑內）。另：本批四個 run 中 checker 升級率 3/4，升級輪條款（🔴 重裁、引文核實、🟡-only 快速路徑）並非罕用路徑，不可視為選配外移。

## §3 投放路徑盤點（硬約束，本 run 自行以 grep 完成）

主 flow 以 `grep -rnE 'eval-flow...' CLAUDE.md README.md AGENTS.md MODEL_POLICY.md install_codex.py skills/*/SKILL.md skills/eval-flow/references/*.md .claude/agents/*.md .claude/hooks/*.py tests/*.py` 盤點。**未派 impact-analyzer**（具名問題觸發屬選配；本盤點為機械 grep、憑據即指令與輸出，留痕於此節）。

### 3.1 被外部**字面引用的節名**（改名即懸空，一律保留原節名）

| 節名 | 外部引用處 |
|---|---|
| 「Tier 1 精簡路徑」 | `CLAUDE.md:36`（兩處）、`skills/parallel-run/SKILL.md:3,49`、`skills/eval-flow/references/formats.md:129` |
| 「Tier 2 路徑」／「Tier 2 完整路徑」 | `CLAUDE.md:37` |
| 「Tier B Bootstrap 路徑」 | `CLAUDE.md:38` |
| 「派工機制」 | `CLAUDE.md:76`、`MODEL_POLICY.md:36`、`formats.md:143` |
| 「Model 指派原則」 | `MODEL_POLICY.md:37` |
| 「主 flow 憑據紀律」 | `.claude/hooks/dispatch.py:327`、`.claude/hooks/report_envelope_check.py:124` |
| 「單一 run 原則」 | `skills/parallel-run/SKILL.md:99` |
| 「Tier 2 [P] fan-out」 | `skills/task-decomposition/SKILL.md:151,153` |
| 「auto-mode 定義」 | `skills/parallel-run/SKILL.md:28` |
| 「前置 1」 | `formats.md:156` |
| 「各前置節」 | `CLAUDE.md:73` |
| 「Tier 1 第 4 點」（直寫捷徑） | `formats.md:61` |

### 3.2 被外部引用的**步驟與子項編號**（編號不可變）

| 編號 | 外部引用處 |
|---|---|
| 循環 step 1（知識前置） | `.claude/agents/retro.md:57,61`、`skills/test-strategy/SKILL.md:132` |
| 循環 step 3 | `.claude/agents/task-verifier.md:3,8,64`、`skills/test-strategy/SKILL.md:134`、`formats.md:88`、`.claude/hooks/eval_state.py:196` |
| 循環 step 5 | `skills/task-decomposition/SKILL.md:190`、`.claude/hooks/eval_gates.py:371` |
| 循環 step 6／step 6 子項② | `skills/eval-flow-resume/SKILL.md:39,50`、`skills/parallel-run/SKILL.md:57`、`skills/test-strategy/SKILL.md:26`、`references/gates.md:9`、`formats.md:16`、`.claude/hooks/eval_gates.py:371` |

### 3.3 檔案路徑引用（分檔時須確認目標端仍讀得到）

- `CLAUDE.md:66,67`：`skills/eval-flow/SKILL.md`（整檔路徑）
- `install_codex.py:29`／`AGENTS.md`：`.agents/skills/eval-flow/SKILL.md`（Codex 部署路徑，整檔）
- `.claude/hooks/eval_gates.py:81`（`SKILL_HINT`）：`skills/eval-flow/SKILL.md`（被 gate 攔截時的提示訊息）
- `init.sh` 第 5 步：`cp -Rf skills/<name>/. ~/.claude/skills/<name>/`——**`references/` 子目錄隨 skill 整包部署**，新增 reference 檔不需改部署腳本（已於 run `2026-10-03-evalflow-dehistorize` 以 glossary.md 實證）

### 3.4 盤點結論

- 節名與步驟編號**全部保留**是本 run 的不變量（§5），任何重排不得改動它們
- 4 個指向節（Tier B／Hotfix／併發／fan-out）**不可合併成單一節**——其中 3 個節名被外部字面引用（3.1）
- 分檔只影響 §3.1 的「前置 1」「各前置節」兩處引用與 `CLAUDE.md:66` 的括註（三處需同 diff 改為指向新檔）

## §4 開放問題（需使用者逐條裁示）

### Q1 — 分檔範圍

| 方案 | 內容 | Tier 1 省下 | 成本與風險 |
|---|---|---|---|
| **A（主 flow 傾向）** | Tier 2 前置四節外移 `references/tier2-prep.md`；本體重排；循環不動 | 2,620 字元（10%） | Tier 2 多讀一檔（一層引用，符合官方 one-level-deep）；3 處外部引用改指向 |
| B | 只重排、不分檔 | 0 | 零引用改動、風險最低；顯著性改善仍得到 |
| C | 連循環細則也外移 | 多，但 Tier 2 不變 | **已於 §2 否決**：硬 gate 離開主載入路徑，違反 R-002 |

主 flow 傾向 A：10% 雖不大，但 Tier 2 前置對 Tier 1 執行者是純雜訊（它永遠不走那條路），而官方 progressive disclosure 的標準做法正是按使用情境分檔。若使用者偏好風險最低，B 亦完整達成「Tier 1 路徑前移」這個主要目的。

### Q2 — 循環 checklist 的形式

官方建議複雜流程附可複製 checklist。風險：checklist 列出「有哪些步驟」，與步驟標題構成同一枚舉的兩份副本，違反 R-007（任何「該做哪些事」的枚舉全 repo 只准一個枚舉點）。

| 方案 | 內容 |
|---|---|
| **a（主 flow 傾向）** | 加 checklist（7 行，每行＝步驟號＋步驟名＋該步的 gate 字），並新增測試強制「checklist 行與步驟標題逐一對應」——以機械防線換取 R-007 風險歸零 |
| b | 不加（R-007 不留任何縫） |
| c | 只給 Tier 2 前置加（前置是線性四步，無步驟編號外部引用） |

### Q3 — 字元預算是否同步收緊

`tests/test_prose_lint.py` 的 `BUDGET_SKILL_CHARS` 現為 28,000（現值 25,384＋10% 餘裕）。方案 A 後本體約 22,800。是否把預算收到 **24,000** 鎖住成果？（收緊的代價：日後要加規則就會先撞預算、被迫分檔——這正是預算的用意。）主 flow 傾向收緊。

### Q4 — dirty tree 歸屬（前置 0 進場檢查）

進場時 `git status --porcelain` 非空：`M run/gate_hits.log`。該檔是 PreToolUse hook 每次攔截時自行 append 的遙測日誌，非本 run 變更。主 flow 傾向**擱置不動**（不納入本 run 的 staging 與 commit）。

## §5 不變量（交付前逐條可機械驗證）

1. **規則句守恆**：變更前（`git show 2838eca:skills/eval-flow/SKILL.md`）的每一條規則行（`-` bullet、數字步驟行、表格 row），在變更後必須出現於 `SKILL.md` 或 `references/tier2-prep.md`；允許的差異只有①新增的導覽／checklist／指向行②行首縮排層級與標題層級（`###`→`##`）③**位置詞／跨檔指向修正**——重排與分檔使「見下／見上／上方／下方／見前置 N」等位置詞機械性失效，修正只改位置詞或補檔名、**不得改動判定式、動詞、對象與條件**，且須逐條留痕於 `run/<run_id>.positional-fixes.md`。以一次性驗證 script 逐行比對，未匹配清單**須與該留痕檔的條目一一對應**（空集合或全為③類）。
2. **節名保留**：§3.1 的 12 個節名在變更後仍存在於 `SKILL.md`（分檔者存在於目標檔），且外部引用處無懸空。
3. **步驟編號保留**：循環步驟仍為 1–7 且語義對應不變；step 6 子項仍為 ⓪①②③；Tier 1 精簡路徑仍為 1–5。
4. **R-NNN 標記集合不變**：`{R-007, R-011, R-012, R-013}`（分檔後取兩檔聯集）。
5. **引用深度一層**：`SKILL.md` → `references/*.md` 一層；`references/` 內不得互相指向（現況 glossary／formats／gates／rare-paths 皆已滿足，新增 tier2-prep.md 同守）。
6. **prose lint 全綠**：`tests/test_prose_lint.py` 無日期、無歷史句、無禁用術語變體、字元預算（含 Q3 裁示後的新值）。
7. **部署副本同步**：收尾後 `./init.sh` 同步 `~/.claude/skills/eval-flow/`，`diff -q` 無差異。

## §6 風險（使用者知情）

- **R-002 投放路徑**（主要風險）：搬動或改指向後，原執行者的載入路徑若讀不到該規則，規則寫了等於沒生效，且**失敗是靜默的**。緩解：§5 不變量 1、2、5 逐條機械驗證；本 run 不改任何規則文字（只搬移、加導覽與 checklist），使「守恆」可機械判定。
- **R-007 單一枚舉點**：checklist 是潛在的第二枚舉點。緩解：Q2 方案 a 的一致性測試。
- **審查成本**：純 prose 重排的 checker 必然升級③（語義保持非存在性可判，本批四個 run 中三次如此）。預期兩輪審查，非異常。
- **殘留風險（不緩解）**：規則句守恆驗證比對「行是否存在」，不驗「行是否在語義正確的位置」。位置錯誤（如把 Tier 2 專屬規則搬進 Tier 1 路徑）只能靠 reviewer 讀 diff 判斷。本 run 接受此殘留，故 step 3 預期走升級輪。

## §7 驗收（對映 task 檔 DoD）

- §5 七條不變量全部有機械憑據
- `python3 -m pytest tests/ -q` 無新增穩定失敗
- 本體 Tier 1 路徑的起始行號 < 循環節起始行號（「前移」的機械判準）
- 檔頭有「路徑選擇」導覽，三個 tier 各一行指向其路徑所在
