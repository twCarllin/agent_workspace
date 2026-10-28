## Writer 相關自驗與 mine 快速模式

```
# Tier 1／2（eval_state.json 存在）：run_id 與測試指令都自動解析
python3 .agent-flow/scripts/test_baseline.py mine

# Tier 0（無 eval_state.json、無 manifest）：兩個旗標都必須給
python3 .agent-flow/scripts/test_baseline.py mine --run-id <任意識別字串> --cmd "<全套測試指令>"
```

- **參數解析順序（實作為準）**：`--run-id` → `eval_state.json` 的 `run_id` → 失敗中止；`--cmd` → `run/<run_id>.json` 的 `test_command` → 失敗中止。故 **Tier 0 兩個都要給**——沒有 eval_state 也沒有 manifest 可查。`--run-id` 在 mine 的唯一用途是定位 manifest 取 `test_command`，給了 `--cmd` 之後它只是為了通過解析（即使明確給 `--cmd` 仍須能解析 run_id）
- **不要傳 `--strike-key`**：該旗標只有 `check` 子命令消費（累犯計數）；mine 端無消費者，傳了會被 argparse 接受但完全忽略

- **用途與分工**：writer 依變更選相關測試，可直接執行派工命令，或用 `run_verify.py` 在相同 run／sub_task 留紀錄，供 step 5 核對與明確重用。mine 只是快速模式，不是唯一准用命令；只選未提交變更中的測試檔，不做 baseline 扣除。既有測試足夠時不必修改測試檔，仍須跑適用的相關測試。範圍外失敗回報主 flow，不自行擴修。
- **範圍推導原理**：每 sub_task 結尾 commit ⇒ writer 開工時樹乾淨 ⇒ 當下 git 未提交變更（staged＋unstaged＋untracked）全屬該 writer，其中的測試檔即其管轄範圍——機械推導，零判斷
- **mine 的範圍限制**：writer 改 source 弄壞既有測試但沒碰測試檔時 mine 不會抓到——writer 須依變更另選相關既有測試，step 5 核對證據範圍並補缺口
- **`[P]` item 的 mine 模式均適用**：`[P]` item 在 fan-out（各開 worktree，隔離樹）或門檻不足的循序退回（逐個執行）下，mine 範圍推導**均成立**（未提交變更只屬當前 item）；兩路徑均無多 writer 並發共樹
- **mine 不落檔**：mine 每次執行不寫任何 `run/` 檔；writer 交付時主 flow 以工作報告的「仲裁記錄」稽核（依 `.agent-flow/roles/code-writer.md`「測試管轄規則」），改測試湊綠的退路由獨立審查核對「需求逐條有適用證據」現形
- writer 端的行為約束（先實作後測試、範圍外失敗照抄不修、仲裁三選一先判再動手、2 次上限帶失敗交付）住在 `.agent-flow/roles/code-writer.md` 的「測試管轄規則」節，不在此重述
