"""eval-flow skill 的結構不變量：防重排／分檔把外部引用打成懸空、或 checklist 與步驟標題漂移。

為什麼需要這支測試：`skills/eval-flow/SKILL.md` 的**節名與步驟編號被 17 處外部引用**
（CLAUDE.md、MODEL_POLICY.md、其他 skill、agent 定義、hook 的錯誤訊息）。改名或改編號不會有任何
錯誤訊息——引用只是靜默指向不存在的東西（R-002：規則須在執行者讀得到的位置）。本檔把這些錨點
釘成測試。

錨點清單的來源與逐處引用位置見 `spec/2026-10-03-evalflow-restructure.md` §3。

執行：python3 -m pytest tests/test_evalflow_structure.py -q
"""
import re
import sys
import unittest
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agent-flow/scripts"))
from document_inventory import skill_documents
SKILL = ROOT / "skills" / "eval-flow" / "SKILL.md"
TIER2_PREP = ROOT / "skills" / "eval-flow" / "references" / "tier2-prep.md"

# 被外部字面引用的錨點（節名／編號項／具名 bullet）。每條後面是引用它的檔案，改動前先讀 Spec §3。
REFERENCED_ANCHORS = (
    ("## 路徑選擇", "本檔導覽的單一枚舉點"),
    ("## 共用：進場檢查", "Tier 1 第 1 點與 tier2-prep.md 前置 0 都指向它"),
    ("## Tier 1 精簡路徑", "CLAUDE.md、parallel-run、formats.md"),
    ("## Tier 2 完整路徑", "CLAUDE.md"),
    ("## 循環", "retro.md／task-verifier.md／test-strategy／formats.md／hooks 以 step N 引用"),
    ("## 派工機制", "CLAUDE.md、MODEL_POLICY.md、formats.md"),
    ("## Model 指派原則", "MODEL_POLICY.md"),
    ("## 主 flow 憑據紀律", "dispatch.py、report_envelope_check.py"),
    ("## 單一 run 原則與併發", "parallel-run"),
    ("## Tier B Bootstrap 路徑", "CLAUDE.md"),
    ("## Tier 2 [P] fan-out", "task-decomposition"),
    ("## 前置 0：初始化", "formats.md、eval-flow-resume"),
    ("## 具名問題觸發", "循環 step 6 子項②"),
    ("## 前置 1：分拆 task", "formats.md、eval-flow-resume、task-decomposer"),
    ("## HITL gate", "formats.md"),
    ("**auto-mode 定義**", "parallel-run 步驟 4"),
    ("4. **主 flow 直寫捷徑", "formats.md 的 executor_notes 欄"),
    ("- ②**冷溯源檔的進版控範圍**", "eval-flow-resume／parallel-run／test-strategy／gates.md／formats.md 皆引用「step 6 子項②」"),
)

CYCLE_HEAD = "## 循環"
NEXT_AFTER_CYCLE = "## 派工機制"
CHECKLIST_LINE = re.compile(r"^- \[ \] step (\d+): (.+?)（gate: .+?）$")
STEP_HEAD = re.compile(r"^(\d)\. (.*)$")


def read(path):
    return path.read_text(encoding="utf-8")


def section(text, start_head, end_head):
    """取 [start_head, end_head) 之間的行（含 start_head 行）。"""
    lines = text.splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith(start_head))
    j = next(n for n, l in enumerate(lines[i + 1:], i + 1) if l.startswith(end_head))
    return lines[i:j]


def cjk_or_ascii_anchors(name):
    """從 checklist 的步驟名取可比對的錨點：長度 ≥3 的中文子串，或長度 ≥4 的 ASCII token。"""
    out = [t for t in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", name)]
    cjk = re.findall(r"[一-鿿]{3,}", name)
    for run in cjk:
        out += [run[k:k + 3] for k in range(len(run) - 2)]
    return out


def anchor_present(text, anchor):
    """節名錨點（`## …`）須是**整行標題**：錨點之後只允許行尾、`（…）` 或 `：…` 這類後綴。

    不可用子串比對——那會讓「## Model 指派原則X」這種附加字元的改名蒙混過關
    （mutation self-check 實測發現：子串版對該 sabotage 不 FAIL）。
    非標題錨點（行中片段，如 `**auto-mode 定義**`）仍用含有比對。
    """
    if not anchor.startswith("## "):
        return anchor in text
    pat = re.compile(r'^' + re.escape(anchor) + r'(?:[（：\s]|$)', re.M)
    return bool(pat.search(text))



LINK = re.compile(r"\[[^\]]+\]\((references/[a-z0-9-]+\.md)\)")
STAGE_LINK = re.compile(r"^\| step (\d)(?:–(\d))? \| \[[^\]]+\]\((references/[a-z0-9-]+\.md)\)", re.M)


def reachable_references(entry):
    """Only actual root links count; orphan files cannot satisfy a safety anchor."""
    found = [entry]
    for rel in dict.fromkeys(LINK.findall(read(entry))):
        target = entry.parent / rel
        if not target.is_file():
            raise FileNotFoundError(f"必要 reference 缺席：{rel}")
        found.append(target)
    return found


def stage_references(entry):
    rows = STAGE_LINK.findall(read(entry))
    covered = [n for first, last, _ in rows
               for n in range(int(first), int(last or first) + 1)]
    if covered != list(range(1, 8)):
        raise ValueError(f"必讀步驟導覽未完整涵蓋 1–7：{covered}")
    return [entry.parent / rel for _, _, rel in rows]


class MandatoryDeliveryTest(unittest.TestCase):
    def test_stage_rules_are_on_mandatory_load_path(self):
        root = read(SKILL)
        self.assertIn("開始當前階段前，必須完整讀取", root)
        self.assertIn("執行前必讀", root)
        refs = reachable_references(SKILL)
        stages = stage_references(SKILL)
        self.assertTrue(all(p in refs for p in stages))
        for p, expected in zip(stages, ({1, 2}, {3, 4}, {5, 6, 7})):
            numbers = [int(m.group(1)) for m in
                       (STEP_HEAD.match(l) for l in read(p).splitlines()) if m]
            self.assertEqual(set(numbers), expected)
            self.assertEqual(len(numbers), len(expected), "實際規則不可重列")

    def test_safety_rules_have_one_reachable_source(self):
        text = "\n".join(read(p) for p in reachable_references(SKILL))
        for anchor in (
            "**四類升級觸發", "**修正迭代上限（僅數升級輪）**",
            "**契約前置與仲裁句（硬性）**", "**知識前置（硬性步驟）**",
            "**發現不得自我授權（scope 防線）**", "**🔴 重裁條款**",
            "**引文核實（重裁不限 🔴）**", "**機械退件門檻**",
            "**冷溯源檔的進版控範圍**", "**`Run-Id: <run_id>` trailer 是硬要求**",
            "**`[憑據:step5]` 條目在本步收口**", "**intent gate（不可鬆）**",
            "**無人看管的 session（headless）不得自行確認**",
        ):
            self.assertEqual(text.count(anchor), 1, f"硬規則缺席或重列：{anchor}")

    def test_missing_reference_is_not_satisfied_by_orphan(self):
        with tempfile.TemporaryDirectory() as d:
            entry = Path(d) / "SKILL.md"
            entry.write_text("[必讀](references/missing.md)")
            with self.assertRaises(FileNotFoundError):
                reachable_references(entry)
            entry.write_text("| step 1–2 | [必讀](references/writing.md) |")
            with self.assertRaises(ValueError):
                stage_references(entry)

    def test_entry_load_is_bounded_and_new_control_is_delivered(self):
        root = read(SKILL)
        self.assertLessEqual(len(root), 5000)
        self.assertIn(".agent-flow/REVIEW_PACKET.md", root)
        self.assertIn(".agent-flow/FLOW_CLI.md", root)
        review = read(SKILL.parent / "references/review.md")
        finish = read(SKILL.parent / "references/testing-finish.md")
        self.assertIn("ready 只表示資料結構與來源可用，不是審查通過", review)
        self.assertIn("失敗、疑似注入與實質疑慮仍依本文件四類升級", review)
        self.assertIn("工具不推定審查通過、不自動 stage", finish)
        self.assertIn("prepare → commit（Run-Id）→ finalize", finish)


class ReferencedAnchorsTest(unittest.TestCase):
    def test_all_externally_referenced_anchors_present(self):
        both = "\n".join(read(p) for p in reachable_references(SKILL))
        missing = [f"{a}（引用者：{who}）" for a, who in REFERENCED_ANCHORS
                   if not anchor_present(both, a)]
        self.assertEqual(missing, [], "外部引用的錨點在 根入口與可到達必讀文件 中缺席或被改名，引用會靜默懸空：\n"
                                      + "\n".join(missing))


class Tier1BeforeCycleTest(unittest.TestCase):
    def test_tier1_path_precedes_shared_cycle(self):
        """Tier 1 佔多數 run，其路徑須排在共用循環之前（本 run 的重排目的）。"""
        lines = read(SKILL).splitlines()
        tier1 = next(n for n, l in enumerate(lines) if l.startswith("## Tier 1 精簡路徑"))
        cycle = next(n for n, l in enumerate(lines) if l.startswith(CYCLE_HEAD))
        self.assertLess(tier1, cycle, f"Tier 1 精簡路徑（L{tier1 + 1}）須排在循環（L{cycle + 1}）之前")


class ReferenceDepthTest(unittest.TestCase):
    def test_reference_files_do_not_point_to_each_other(self):
        """官方 progressive disclosure：引用只准一層（SKILL.md → references/）。

        references 互指會讓 Claude 以 head -N 預覽巢狀檔、讀到不完整內容。指向上層
        SKILL.md 或別的 skill 不算互指。
        """
        offenders = []
        for f in skill_documents(ROOT):
            if f.parent.name != "references":
                continue
            for hit in set(re.findall(r"references/([a-z0-9-]+\.md)", read(f))):
                if hit != f.name:
                    offenders.append(f"{f.relative_to(ROOT)} → references/{hit}")
        self.assertEqual(offenders, [], "references 互相指向（引用深度 >1）：\n" + "\n".join(offenders))


class CycleChecklistTest(unittest.TestCase):
    def test_checklist_matches_step_headings(self):
        """checklist 與步驟標題是同一枚舉的兩份副本（R-007）——以本測試代替人工同步。"""
        cycle = section(read(SKILL), CYCLE_HEAD, NEXT_AFTER_CYCLE)
        real_steps = "\n".join(read(p) for p in stage_references(SKILL))
        checklist = [CHECKLIST_LINE.match(l) for l in cycle]
        checklist = [m for m in checklist if m]
        heads = {int(m.group(1)): m.group(2) for m in
                 (STEP_HEAD.match(l) for l in real_steps.splitlines()) if m}

        self.assertEqual([int(m.group(1)) for m in checklist], [1, 2, 3, 4, 5, 6, 7],
                         "checklist 須恰 7 行、step 編號 1–7 依序")

        # DoD 字面要求 checklist 放在 fenced code block 內（才能整塊複製進回報，
        # 且 prose lint 的日期／術語掃描會跳過 fence）——此斷言守護該字面要求。
        fences = [i for i, l in enumerate(cycle) if l.startswith("```")]
        idx = [i for i, l in enumerate(cycle) if CHECKLIST_LINE.match(l)]
        self.assertGreaterEqual(len(fences), 2, "循環節的 checklist 須放在 fenced code block 內（未找到成對 fence）")
        self.assertTrue(all(fences[0] < i < fences[1] for i in idx),
                        f"checklist 行須全部落在第一組 fence 之間（fence 行號 {fences[:2]}，checklist 行號 {idx}）")
        self.assertEqual(sorted(heads), [1, 2, 3, 4, 5, 6, 7],
                         f"循環須恰 7 個數字步驟，實得 {sorted(heads)}")

        mismatch = []
        for m in checklist:
            n, name = int(m.group(1)), m.group(2)
            anchors = cjk_or_ascii_anchors(name)
            if not any(a in heads[n] for a in anchors):
                mismatch.append(f"step {n}: checklist「{name}」的錨點 {anchors} 都不在步驟標題內")
        self.assertEqual(mismatch, [], "checklist 與步驟標題漂移：\n" + "\n".join(mismatch))


if __name__ == "__main__":
    unittest.main()
