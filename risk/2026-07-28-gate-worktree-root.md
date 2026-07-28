# 風險分析報告：2026-07-28-gate-worktree-root

對象 Spec：`spec/2026-07-28-gate-worktree-root.md`（修正 hook gate 在 git worktree 下解析錯工作區）

**不適用：資料**（不觸及任何 DB、schema、migration 或持久化資料格式；本變更只影響 hook 進程解析工作目錄的方式）

---

## 1. 技術風險 🟡

**風險描述**

修正需在 `run_hook()` 內以 `git rev-parse --show-toplevel` 解析工作區根。這在 hook 熱路徑上引入一個對外部指令（`git`）的相依：`git` 不在 PATH、儲存庫損毀、或指令逾時，都會使解析失敗。

另有一個較隱蔽的相依：`gate-check.sh` 每次呼叫都重新 `python3 eval_gates.py`，**不快取**。因此本檔一經存檔即對後續所有 gate 生效，沒有「改完再重啟才套用」的緩衝期。

**對策**

- `subprocess.run` 一律帶 `timeout`，並以 `try/except (OSError, subprocess.SubprocessError)` 包覆；任何失敗一律退回現行的 `CLAUDE_PROJECT_DIR` 路徑，不得讓解析失敗變成例外向外拋。
- 以參數 list 形式呼叫（`["git", "-C", cwd, "rev-parse", "--show-toplevel"]`），不經 shell。
- 修改後、依賴新行為前，先獨立驗證 `python3 -c "import eval_gates"` 可正常匯入。

## 2. 安全風險 🟢

**風險描述**

`payload.cwd` 來自 hook 的 stdin JSON，屬**外部可控輸入**，而修正後它會被當成路徑傳給 `git -C`。需確認不構成指令注入或路徑逃逸。

**評估與對策**

- 以參數 list 呼叫、不經 shell，`cwd` 內容不會被解讀為指令，無注入面。
- 路徑逃逸在此情境無實質意義：payload 由 Claude Code 產生而非遠端使用者，且 hook 本就以當前使用者權限執行；`git rev-parse` 為唯讀操作。
- 不涉及驗證／授權邏輯、不接觸密碼／token／PII、不新增環境變數或金鑰。
- 唯一需守的界線：解析結果只用於 `os.chdir`，**不得**用於組字串執行任何 shell 指令。

## 3. 效能風險 🟡

**風險描述**

hook 的 matcher 是 `Bash|Task|Agent`，即**每一次** Bash 指令與 subagent 呼叫都會觸發。新增一次 `git rev-parse` 子進程，等於在所有工具呼叫上加一筆固定延遲（實測量級約數十毫秒，但在長 run 中會累積數百次）。

**對策**

- 僅在必要時呼叫：先取 `CLAUDE_PROJECT_DIR`，僅當需要判斷「是否為不同工作區」時才執行 `git rev-parse`（見面向 6 的設計）。
- 設定明確 `timeout`（5 秒），避免 git 卡住時整個工具呼叫被拖住。
- 不引入快取機制——跨進程快取需額外落檔，複雜度與收益不成比例（違反 CLAUDE.md「簡單優先」）。

## 4. 部署風險 🟡

**風險描述**

三點：

1. **立即生效、無緩衝**：`eval_gates.py` 存檔當下即對本 run 自身的後續 gate 生效，包含本 run 收尾時的 commit gate。等同「在飛行中更換自己的安全網」。
2. **崩潰時靜默失效**：hook 的 exit code 語義為 `0` 放行、`2` 攔截、**其他值視為非阻斷性錯誤（工具照常執行）**。因此若修正引入未捕捉例外，`gate-check.sh` 會以非 2 的碼結束 → gate **靜默停止攔截**（fail-open），而非鎖死 session。這比鎖死更危險，因為不會被立即發現。
3. **部署副本不同步**：`skills/` 在 `~/.claude/skills/` 有一份 inode 不同的內容副本。只改 repo 內的 SKILL.md，執行期讀到的仍是舊版。

**對策**

- 對策 1／2：所有新增邏輯以「失敗即退回現行行為」為預設；完成修改後**立刻**以構造 payload 直接執行 `eval_gates.py --hook` 驗證三種情境（同工作區、跨 worktree、非 git 目錄）皆回傳預期 exit code，確認未 fail-open 後才繼續往下。
- 對策 2 補充：復原路徑存在且不受 hook 影響——hook 只攔截 Claude 的 Bash 工具，使用者可在自己的終端 `git checkout .claude/hooks/eval_gates.py` 還原。
- 對策 3：列為 DoD 第 8 條，收尾前執行同步並留痕。
- 符合「禁止未經本地測試直接部署」：本 run 的 step 5 走全套測試 gate，不豁免。

## 5. 業務與維護風險 🟡

**風險描述**

**最大的 regression 面：`CLAUDE_PROJECT_DIR` 為 git 儲存庫子目錄的情境。**

若某專案的 session 啟動於 git repo 的子目錄（`flow` 相關檔案放在 `<repo>/subproject/` 下），現行行為是 `chdir` 到該子目錄、以子目錄的 `run/` 與 `eval_state.json` 判定。若修正改為「一律解析到 git 工作區根」，該情境的 gate 會突然改看 repo 根目錄，狀態檔全部找不到 → 既有專案的 flow 全面誤擋。

次要面：`payload` 缺 `cwd` 欄位的舊版／非預期輸入不可拋例外。

**對策（本面向的對策同時是實作的設計約束，須帶入 task item 備註）**

採**最小偏離設計**：只有在確認「tool call 來自與 `CLAUDE_PROJECT_DIR` **不同的** git 工作區」時才改變行為，其餘一律回傳 `CLAUDE_PROJECT_DIR`，行為與修改前逐位元相同。

```
cwd_top = git_toplevel(payload.cwd)
cpd_top = git_toplevel(CLAUDE_PROJECT_DIR)
若 兩者皆解析成功 且 cwd_top != cpd_top  → 回傳 cwd_top   （跨 worktree，唯一改變行為的分支）
否則                                      → 回傳 CLAUDE_PROJECT_DIR（含子目錄情境，行為不變）
```

如此：
- 主工作區（含 `CLAUDE_PROJECT_DIR` 為子目錄）→ 行為不變，DoD 5 自動滿足。
- 跨 worktree → 解析到該 worktree 根，DoD 1／2 滿足。
- 非 git 或 git 不可用 → 退回 `CLAUDE_PROJECT_DIR`，DoD 3 滿足。
- 無 `cwd` 欄位 → `payload.get("cwd")` 回 `None`，退回 `os.getcwd()` 後同上，DoD 4 滿足。

向後相容性：不改任何 gate 的判定規則、不改 manifest／`eval_state.json` 格式、不改 `.claude/settings.json` 註冊方式。既有 run 的歸檔檔不受影響。

對使用者的可見影響：`parallel-run` 與 `[P]` fan-out 從「文件宣稱可用但實際失效」變為真正可用；兩份 SKILL.md 的錯誤敘述須一併更正，否則文件與行為的落差會再次誤導接手者。

---

## 結論

**無 🔴 重大風險**，可進入前置 2。

🟡 中等風險共 4 項（技術、效能、部署、業務維護），對策均已具體化；其中**面向 5 的「最小偏離設計」是實作的硬性約束**，須於分拆 task 時帶入對應 item 的備註——若實作改成「一律解析到 git 根」，將對子目錄型專案造成全面誤擋。

面向 4 的「崩潰即 fail-open」須於 step 5 前以構造 payload 實測確認，不可只靠單元測試推定。
