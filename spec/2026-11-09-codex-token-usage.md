# Codex run token 計量

## 目標與驗收
使用者執行 `token_usage.py <run_id> --write` 後，可在 manifest 與 stats 報表看見主 session、子 agent、前置／循環用量與資料完整度。重算結果相同；重疊來源不重複計數；無法歸屬的量明示未知。實際金額不在本次範圍。

## 既有行為與證據
- `token_usage.py:305-317` 對 Codex 直接回報 unsupported_codex。
- `eval_state.py:108-121` 只從 CLAUDE_CODE_SESSION_ID 登記主 session。
- `dispatch.py:179-190,331-347` 留存 Codex CLI 用量與 session。
- `stats.py:678-703` 報告既有用量狀態與 prep/loop 比。
- 本機近期 rollout JSONL 有 event_msg/token_count/info.total_token_usage（查詢：讀取 ~/.codex/sessions 最近三檔，三檔皆有 token_events）。

## 設計與影響
以主 session ID 與 run events 時窗切累積 token_count；差額按時間窗求和，不加總每筆累積值。子 agent 以 session ID 去重；dispatch 已有用量者優先使用其派工回執。缺失主 session 身分或時窗時狀態為 partial 或 unknown，不能填零。報表將 token 數與金額分開。涉及 `token_usage.py`、`eval_state.py`、`dispatch.py`、`stats.py`、`FLOW_CLI.md` 與相關測試；舊 Claude 計量保持相容。Codex rollout 為本機格式，缺欄時回報未知，不能聲稱完整。

## 決策
採用先前使用者確認的修改計畫：統計每個 run、角色與階段；保留來源及缺口；實測真實紀錄與回歸。工程細節由主 flow 決定。
