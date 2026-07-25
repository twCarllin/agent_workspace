# Flow 改進 Backlog（2026-07-25 整理）

> 來源：兩個長 run 的實戰教訓（本 repo tier2-p-worktree run ＋ 使用者另一 14-sub_task run）。
> 已落地：task-verifier 退役＋reviewer 完成度節、主 flow 憑據紀律、resume 對賬、測試預算（契約表上下限）——見 2026-07-25 未 commit 變更。
> 以下為**待做**項，每項自足可讀，任何 session 可接手。

## 1. 粒度合併：Tier 2 補「小 prose item 合併一輪審」規則
在 `skills/eval-flow/SKILL.md` 的 Tier 2 路徑補上 Tier 1 已有的「小 prose item 合併」規則：語義同源的小 prose item 併成一個 sub_task 一輪審。**最大單一省稅槓桿**（item 數近乎砍半，token＋時間雙省）。附合併判準（什麼能合／不能合），避免為省稅把該分開審的混在一起。實測依據：2026-07-25 run 10 個 sub_task 合理粒度為 4–5 個。

## 2. 複檢從簡（殘餘）：🟡 修正後聚焦驗修正點
verifier 退役後重跑已從 2 隻降 1 隻；殘餘優化：🟡 級修正後的複審 prompt 聚焦修正點（完成度結論若不受修正影響則沿用），不全量重審。🔴 級照舊全審（修正可能改行為）。落點：`skills/eval-flow/SKILL.md` 循環 step 4。

## 3. 流水線重疊：review(N) 背景跑時同時派 writer(N+1)
file-scoped diff 已解掉互踩問題——review(N) 在背景跑時主 flow 同時派 writer(N+1)。純省 wall-clock（30–40%），token 不變。注意：writer(N+1) 的 git add 須等 review(N) 取完 diff，或確保兩者 files 不相交。落點：`skills/eval-flow/SKILL.md`。

## 5. 半殘協定：writer 異常結束禁止沿用其宣稱
`skills/eval-flow/SKILL.md` 加硬規則：writer 回報異常（額度中斷／截斷／空回報）→ 一律實測其產出、盤點缺口，再決定接手或重派；不得沿用其任何宣稱。程序已於 2026-07-25 run sub_task 6（月度額度中斷）實戰驗證，僅差落成文字。

## 6. RETRO 條目加「reviewer 檢查點」欄
retro agent 定義＋eval-flow step 3：每條 RETRO 教訓沉澱時同步寫出 reviewer 該問的那一句；主 flow 派審時把命中的檢查點貼進 reviewer prompt。教訓來源：約束原文貼進 writer prompt 仍犯，reviewer 端列為審點才攔住——writer 是第一層，reviewer 才是閉環。

## 7. 可逆突變驗證寫進 review-checklist
review-checklist skill＋code-reviewer 定義：reviewer 可對 production code 做可逆突變驗證測試鑑別力（實跑突變→主測試應 FAIL→還原）。安全欄杆：驗完必還原、以 `git diff` 證明零殘留、殘留＝審查報告作廢。教訓來源：三個 🔴 全是「靜態讀不出、實跑才炸」，突變驗證是鑑別力最高的手段。

---
（編號沿原 todo；#4 resume 對賬、#8 測試預算已完成，不列。）
