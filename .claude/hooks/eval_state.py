#!/usr/bin/env python3
"""eval_state.json 操作 helper：eval-flow 循環的欄位更新一律走這裡，不手動 Edit。

用法：
  python3 .claude/hooks/eval_state.py init --run-id ID
  python3 .claude/hooks/eval_state.py add-subtask --id N --name "名稱"
  python3 .claude/hooks/eval_state.py set-step <id> <writing|reviewing|fixing|verifying|testing|done>
  python3 .claude/hooks/eval_state.py set-files <id> <file...>
  python3 .claude/hooks/eval_state.py set-test <id> (--passed --evidence "指令＋結果摘要" | --failed)
  python3 .claude/hooks/eval_state.py set-status <id> <passed|failed|in_progress> [--warning]
  python3 .claude/hooks/eval_state.py set-review <id> <reds> [--dimensions '<json>']
                                                   # step 3 首輪 code-reviewer 🔴 數（修正前原始數）
                                                   # --dimensions: 維度→問題數，如 '{"Clarity":1,"Completeness":2}'
  python3 .claude/hooks/eval_state.py set-verify <id>          # step 4 reviewer 完成度節通過時呼叫
  python3 .claude/hooks/eval_state.py add-verification <id> --command "<指令>" --exit-code <int>
                                                   # step 5 每跑一條驗證指令 append 一筆（純記錄，無 gate）
  python3 .claude/hooks/eval_state.py list-files      # 所有 sub_task files 聯集（餵 related --files）
  python3 .claude/hooks/eval_state.py archive         # 驗證後歸檔 run/<run_id>.eval.json 並刪除 eval_state.json

archive 前驗證全部 sub_task passed 且測試欄位齊備（同 eval_gates 的 commit gate 標準），
驗證不過即 exit 2 不落盤。exit 0 = 成功；exit 1 = 使用錯誤；exit 2 = 驗證不過。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import eval_gates  # noqa: E402

STATE_PATH = "eval_state.json"
STEPS = ["writing", "reviewing", "fixing", "verifying", "testing", "done"]
STATUSES = ["passed", "failed", "in_progress"]


def fail(msg, code=1):
    print(f"[eval-state] {msg}", file=sys.stderr)
    sys.exit(code)


def load():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        fail(f"{STATE_PATH} 不存在：先跑 init（前置 0）")
    except json.JSONDecodeError as e:
        fail(f"{STATE_PATH} 非合法 JSON（{e}）")


def save(state, path=STATE_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


EVENTS_ARG_TRUNCATE_LEN = 200


def _truncate_value(v):
    if isinstance(v, str) and len(v) > EVENTS_ARG_TRUNCATE_LEN:
        return v[:EVENTS_ARG_TRUNCATE_LEN] + "…[truncated]"
    if isinstance(v, list):
        return [_truncate_value(x) for x in v]
    return v


def append_event(run_id, cmd_name, args):
    """2a：寫入子命令成功後的事件留痕（旁路）。append 必須發生在 save() 成功之後，
    失敗僅 stderr warning、不改主子命令的 exit code（風險技術#1：旁路不得變主路）。"""
    if not run_id:
        print(f"[eval-state] 警告：run_id 缺失，略過事件記錄（cmd={cmd_name}）", file=sys.stderr)
        return
    try:
        event = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "cmd": cmd_name,
            "args": {k: _truncate_value(v) for k, v in vars(args).items()
                     if k not in ("func", "command")},
        }
        os.makedirs("run", exist_ok=True)
        with open(os.path.join("run", f"{run_id}.events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[eval-state] 警告：事件記錄寫入失敗（{e}），不影響本次操作", file=sys.stderr)


def record_session(run_id):
    """init 事件時把本 session 的對應鍵寫進 manifest 選填欄 session_id／config_dir
    （token_usage.py 憑此開對應 transcript）。旁路：env 缺、manifest 缺或壞、寫入失敗
    皆只 stderr warning、不改 exit code（同 append_event 慣例）；已有值不覆寫（resume
    換 session 不得改寫首次 session）。"""
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session_id:
        return
    path = os.path.join("run", f"{run_id}.json")
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        if manifest.get("session_id"):
            return
        manifest["session_id"] = session_id
        manifest["config_dir"] = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
        save(manifest, path)
    except Exception as e:
        print(f"[eval-state] 警告：session 對應鍵未寫入 manifest（{e}），不影響本次操作", file=sys.stderr)


def find_subtask(state, sid):
    """頂層 id＝task id（Q2，2026-09-22 起 sub_tasks 一筆＝一個 task，此前一筆＝一個 item）。
    `eval_state` 不存 item 層資料（Q10 裁示）——item 的 DoD／契約表 single source 是 task 檔，
    故無 item 層定位入口，也不該在此新增一個。"""
    for st in state.get("sub_tasks", []):
        if st.get("id") == sid:
            return st
    fail(f"找不到 id={sid} 的 sub_task")


def cmd_init(args):
    if os.path.exists(STATE_PATH):
        fail(f"{STATE_PATH} 已存在：一個 worktree 同時只跑一個 run，先收尾或歸檔既有 run")
    save({"run_id": args.run_id, "sub_tasks": []})
    append_event(args.run_id, "init", args)
    record_session(args.run_id)
    print(f"[eval-state] init: run_id={args.run_id}")


def cmd_add_subtask(args):
    """一筆＝一個 task（Q2，2026-09-22 起）。status／step／files 與憑據四欄
    （local_test_passed／local_test_evidence／review_reds／verify_passed）全記在這一層——
    審查與測試都以 task 為單位，故無 per-item 欄位。item 的 DoD／契約表不在此重複存放
    （Q10：single source＝task 檔）；`risk_analysis` 已隨前置 1 刪除而移除（Q8）。
    鍵集由 tests/test_eval_state.py 的 skeleton 測試逐鍵鎖定，增刪欄位會使該測試紅。"""
    state = load()
    if any(st.get("id") == args.id for st in state["sub_tasks"]):
        fail(f"id={args.id} 已存在")
    state["sub_tasks"].append({
        "id": args.id, "name": args.name, "status": "in_progress", "step": None,
        "files": [], "warning": False,
        "local_test_passed": False, "local_test_evidence": None,
        "verification_commands": [],
        "review_reds": None, "verify_passed": False,
        "review_dimensions": None, "checked_by": None,
    })
    save(state)
    append_event(state.get("run_id"), "add-subtask", args)
    print(f"[eval-state] add-subtask: {args.id}「{args.name}」")


def cmd_set_step(args):
    state = load()
    find_subtask(state, args.id)["step"] = args.step
    save(state)
    append_event(state.get("run_id"), "set-step", args)
    print(f"[eval-state] sub_task {args.id} step -> {args.step}")


def cmd_set_files(args):
    state = load()
    find_subtask(state, args.id)["files"] = list(dict.fromkeys(args.files))
    save(state)
    append_event(state.get("run_id"), "set-files", args)
    print(f"[eval-state] sub_task {args.id} files -> {len(args.files)} 個檔案")


def cmd_set_test(args):
    state = load()
    st = find_subtask(state, args.id)
    if args.passed:
        if not (args.evidence and args.evidence.strip()):
            fail("--passed 必須帶 --evidence（指令＋結果摘要）")
        st["local_test_passed"] = True
        st["local_test_evidence"] = args.evidence
    else:
        st["local_test_passed"] = False
        if args.evidence:
            st["local_test_evidence"] = args.evidence
    save(state)
    append_event(state.get("run_id"), "set-test", args)
    print(f"[eval-state] sub_task {args.id} local_test_passed -> {st['local_test_passed']}")


def cmd_set_status(args):
    state = load()
    st = find_subtask(state, args.id)
    st["status"] = args.status
    if args.warning:
        st["warning"] = True
    save(state)
    append_event(state.get("run_id"), "set-status", args)
    print(f"[eval-state] sub_task {args.id} status -> {args.status}")


VALID_DIMENSIONS = {"Clarity", "Completeness", "Testability", "Non-functional", "Technical_constraints"}
# 審定者留痕（checker 化，2026-09-06）：checker＝checker 輪直過；reviewer:①-⑤＝升級輪（碼見 eval-flow step 3）；
# reviewer:manual＝手動觸發；reviewer:boundary＝理由碼含邊界類的 run 直派 reviewer（2026-09-21，不計升級率）
VALID_CHECKED_BY = {"checker", "reviewer:①", "reviewer:②", "reviewer:③", "reviewer:④", "reviewer:⑤",
                    "reviewer:manual", "reviewer:boundary"}


def cmd_set_review(args):
    if args.reds < 0:
        fail(f"reds 必須為非負整數（收到 {args.reds}）")
    dims = None
    if args.dimensions is not None:
        try:
            dims = json.loads(args.dimensions)
        except json.JSONDecodeError as e:
            fail(f"--dimensions 非合法 JSON（{e}）", code=2)
        if not isinstance(dims, dict):
            fail("--dimensions 必須為 JSON 物件（維度→問題數）", code=2)
        for k, v in dims.items():
            if k not in VALID_DIMENSIONS:
                fail(
                    f"--dimensions 含非法維度鍵「{k}」；"
                    f"合法值：{', '.join(sorted(VALID_DIMENSIONS))}",
                    code=2,
                )
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                fail(f"--dimensions 維度「{k}」的值必須為非負整數（收到 {v!r}）", code=2)
    if args.checked_by is not None and args.checked_by not in VALID_CHECKED_BY:
        fail(
            f"--checked-by 含非法值「{args.checked_by}」；"
            f"合法值：{', '.join(sorted(VALID_CHECKED_BY))}",
            code=2,
        )
    state = load()
    st = find_subtask(state, args.id)
    st["review_reds"] = args.reds
    if dims is not None:
        st["review_dimensions"] = dims
    if args.checked_by is not None:
        st["checked_by"] = args.checked_by
    save(state)
    append_event(state.get("run_id"), "set-review", args)
    msg = f"[eval-state] sub_task {args.id} review_reds -> {args.reds}"
    if dims is not None:
        msg += f"，review_dimensions -> {dims}"
    if args.checked_by is not None:
        msg += f"，checked_by -> {args.checked_by}"
    print(msg)


def cmd_set_verify(args):
    state = load()
    find_subtask(state, args.id)["verify_passed"] = True
    save(state)
    append_event(state.get("run_id"), "set-verify", args)
    print(f"[eval-state] sub_task {args.id} verify_passed -> True")


def cmd_add_verification(args):
    """step 5 的驗證指令留痕（append 累積）。純記錄欄位、不被任何 gate 消費——
    與 local_test_evidence 並存：後者記推理留痕（散文），本欄記「跑了哪些指令、結果如何」。"""
    if not args.command.strip():
        fail("--command 不可為空字串")
    state = load()
    st = find_subtask(state, args.id)
    # 舊 eval_state.json 的 sub_task 無此鍵（本欄位為後加的可選欄位）→ 補上再 append
    st.setdefault("verification_commands", []).append(
        {"command": args.command, "exit_code": args.exit_code}
    )
    save(state)
    # 事件鍵用 verify_command：append_event 會過濾 `command` 鍵（與子命令 dest 同名），
    # 直接傳 args 會讓事件只剩 exit_code（2026-09-21 修正；消費端 stats.py 全套次數）
    append_event(state.get("run_id"), "add-verification",
                 argparse.Namespace(id=args.id, verify_command=args.command, exit_code=args.exit_code))
    print(f"[eval-state] sub_task {args.id} verification_commands "
          f"+1（共 {len(st['verification_commands'])} 筆）exit={args.exit_code}")


def cmd_list_files(args):
    state = load()
    seen = {}
    for st in state.get("sub_tasks", []):
        for f in st.get("files", []):
            seen[f] = True
    if seen:
        print("\n".join(seen))


def cmd_event(args):
    """Tier 1 事件留痕：Tier 1 不建 eval_state.json，本子命令不經 load()，
    直接沿用 append_event 寫 run/<run_id>.events.jsonl（R-009：沿用同路徑既有 helper）。"""
    append_event(args.run_id, args.name, args)
    if args.name == "init":
        record_session(args.run_id)
    print(f"[eval-state] event: {args.name} -> run/{args.run_id}.events.jsonl")


def _manifest_path(run_id):
    return os.path.join("run", f"{run_id}.json")


# 無人看管判定：headless（`claude -p`）的 CLAUDE_CODE_SESSION_ATTENDED 為 "0"、互動 session 為 "1"
# （2026-10-03 實測：互動 ENTRYPOINT=cli／ATTENDED=1；headless ENTRYPOINT=sdk-cli／ATTENDED=0）。
# 取 ATTENDED 不取 ENTRYPOINT：前者直接表達「有人在看」這個語義，後者會隨整合方式（vscode、sdk-py）變動。
ATTENDED_ENV = "CLAUDE_CODE_SESSION_ATTENDED"


def _session_attended():
    """回傳 True／False／None（環境未提供該變數，無法判定）。"""
    raw = os.environ.get(ATTENDED_ENV)
    if raw is None or raw == "":
        return None
    return raw not in ("0", "false", "False")


def cmd_hitl_confirm(args):
    """HITL 確認只認檔不認對話：寫 manifest 的三欄並把 phase 推進 decomposed。

    為何是指令而不是手動 Edit：確認是 gate 的唯一憑據（eval_gates 的 Write／Edit 直寫 gate 憑
    phase 放行），手寫容易漏欄或在 intent gate 未過時就推進。前置不過一律 exit 1 不寫檔。

    **無人看管的 session 不得自行確認**（出生證：評測情境 tier1-hitl-stop 實測——headless session
    自己跑了本指令把 phase 推進 decomposed，再動工，gate 形同虛設）。依 CLAUDE.md 防濫用規則既有
    原則（驗證豁免與 all-in 皆「agent 不可自行認定」），無人可確認時確認本身不成立。
    此檢查防的是「照規則推進」的誤用，不防刻意偽造環境變數的對手——與本框架其他 gate 同一防護層級。
    """
    note = (args.note or "").strip()
    if not note:
        fail("--note 不可為空：須記「時間＋確認範圍一句話」供接手者驗證")
    path = _manifest_path(args.run_id)
    if not os.path.exists(path):
        fail(f"{path} 不存在：run_id 打錯或前置 0 未完成")
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        fail(f"{path} 無法讀取或非合法 JSON（{e}）")
    if not isinstance(m, dict):
        fail(f"{path} 內容不是 JSON 物件")
    if m.get("status") != "in_progress":
        fail(f"{path} status 為 {m.get('status')!r}，非 in_progress：只有進行中的 run 需要 HITL 確認")
    if not (m.get("spec_path") or m.get("spec_inline")):
        fail(f"{path} intent gate 未過：spec_path 與 spec_inline 皆空，不可確認計畫")
    if not m.get("task_file"):
        fail(f"{path} task_file 為空：HITL 掛在分拆之後，先建 task 檔再確認")
    if m.get("hitl_confirmed_at"):
        fail(f"{path} 已有 hitl_confirmed_at（{str(m['hitl_confirmed_at'])[:60]}…）："
             f"不覆蓋既有確認時間；計畫若有變更，請人工在 manifest 追記並說明")
    current = eval_gates.manifest_phase(m)
    if eval_gates.PHASES.index(current) >= eval_gates.PHASES.index("decomposed"):
        fail(f"{path} phase 已是 {current}（≥ decomposed）：本指令只把 init 推進到 decomposed，"
             f"不可把已前進的 phase 倒退回去")
    attended = _session_attended()
    if attended is False:
        # 訊息不印環境變數名：被擋的一方不需要知道哪個變數決定了判定（名稱留在註解與測試）
        fail("無人看管的 session 不得自行確認 HITL：沒有人可以確認，確認本身不成立\n"
             f"→ 正確行為：停在這一步，把「N tasks／M items」計畫與待裁示項回報，結束本次執行；"
             f"由有人看管的 session 接手（依 eval-flow-resume 讀檔續跑）")
    m["hitl_confirmed_at"] = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} — {note}"
    m["hitl_rulings"] = args.rulings
    m["hitl_attended"] = attended  # True＝互動 session 確認；None＝環境未提供該變數（留痕供稽核）
    m["phase"] = "decomposed"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
    append_event(args.run_id, "hitl_confirmed", args)
    print(f"[eval-state] {args.run_id} HITL 已確認：phase -> decomposed，裁示 {args.rulings} 條")


TIER0_LOG = os.path.join("run", "tier0.jsonl")

# Tier 0 判準（CLAUDE.md Router 第二步，單一枚舉點在該檔；此處為機械執行）
TIER0_MAX_FILES = 3
TIER0_MAX_LINES = 80
TIER0_MECHANICAL_MAX_LINES_PER_FILE = 50


def _git_changed_lines(files):
    """回傳 {path: 增＋刪行數}。已追蹤檔走 `git diff HEAD --numstat`，未追蹤檔以行數計為全新增。

    為何是 HEAD 而非工作區 diff：Tier 0 不 commit，變更可能在工作區也可能已 git add，
    `git diff HEAD` 同時涵蓋兩者（與 CLAUDE.md「以 git diff 變更行數計」一致）。
    二進位檔的 numstat 欄位是 `-`，以 0 計並在回報中可見（Tier 0 不該改二進位檔）。
    """
    r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
    if r.returncode != 0 or r.stdout.strip() != "true":
        fail("不在 git 工作區：Tier 0 留痕的行數須由 git diff 核算，無法核算即不記帳")
    dirs = [f for f in files if os.path.isdir(f)]
    if dirs:
        # 目錄 pathspec 會讓檔數上限失效：len(files) 只數使用者給的清單長度，而 git diff 會
        # 展開目錄下的全部檔案（實測：--files d 底下 5 檔各改 1 行 → 檔數上限 3 被繞過）
        fail(f"--files 不接受目錄（檔數上限會失效）：{'、'.join(sorted(dirs))}；請逐檔列出")
    out = {}
    r = subprocess.run(["git", "diff", "HEAD", "--numstat", "--"] + list(files),
                       capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"git diff 失敗：{r.stderr.strip()[-200:]}")
    binary = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        if add == "-" or dele == "-":
            # numstat 對二進位檔回 `-`：以 0 計會讓任意大小的二進位改動偷渡過行數上限，
            # 且 lines_verified 會變成不誠實的宣稱。Tier 0 不該改二進位檔，直接拒絕。
            binary.append(path)
            continue
        out[path] = (int(add) if add.isdigit() else 0) + (int(dele) if dele.isdigit() else 0)
    if binary:
        fail(f"二進位檔的變更行數無法核算，Tier 0 不該改二進位檔：{'、'.join(sorted(binary))}")
    # 存在性檢查放在 diff 之後：被刪除的檔在工作區不存在，但 git diff HEAD 看得到（合法的
    # Tier 0 刪檔），只有「工作區沒有、diff 也沒有」才是打錯路徑
    missing = [f for f in files if not os.path.exists(f) and f not in out]
    if missing:
        fail(f"--files 列出的路徑不存在、git diff 也無此變更（可能是打錯路徑）："
             f"{'、'.join(missing)}")
    for f in files:
        if f in out:
            continue
        # 未追蹤（git diff HEAD 看不到）→ 全檔視為新增行
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", f],
                                 capture_output=True, text=True).returncode == 0
        if tracked:
            out[f] = 0  # 已追蹤但無差異
        else:
            try:
                with open(f, "rb") as fh:
                    out[f] = sum(1 for _ in fh)
            except OSError as e:
                fail(f"讀不到未追蹤檔 {f}（{e}）")
    return out


def cmd_tier0(args):
    """Tier 0 收尾留痕：append 一行到 run/tier0.jsonl。

    行數**自算**不收信自報（Tier 0 直寫無任何 gate，自報數字從未被核對），並機械執行
    CLAUDE.md Router 的兩條可判準則：檔數 ≤3、合計 ≤80 行（`--mechanical` 例外改為每檔 ≤50、
    不限檔數）。「無新行為」「不觸信任邊界」兩條無法機械判定，仍由使用者於 commit 前把關。
    留痕本身仍是純記錄、非判定基準（R-010）。
    """
    if not args.summary.strip():
        fail("--summary 不可為空字串")
    files = [f.strip() for f in args.files.split(",") if f.strip()]
    if not files:
        fail("--files 為空")
    per_file = _git_changed_lines(files)
    total = sum(per_file.values())
    if args.lines != total:
        fail(f"--lines 與 git diff 實得不符：自報 {args.lines}／實得 {total}"
             f"（逐檔：{'、'.join(f'{k} {v}' for k, v in sorted(per_file.items()))}）")
    if args.mechanical:
        over = {k: v for k, v in per_file.items() if v > TIER0_MECHANICAL_MAX_LINES_PER_FILE}
        if over:
            fail(f"機械式改動例外要求每檔 ≤{TIER0_MECHANICAL_MAX_LINES_PER_FILE} 行，超標："
                 f"{'、'.join(f'{k} {v}' for k, v in sorted(over.items()))}")
    else:
        if len(files) > TIER0_MAX_FILES:
            fail(f"Tier 0 上限為 {TIER0_MAX_FILES} 個檔案，本次 {len(files)} 個："
                 f"同一種機械式改動跨多檔請加 --mechanical，否則應判 Tier 1")
        if total > TIER0_MAX_LINES:
            fail(f"Tier 0 上限為合計 {TIER0_MAX_LINES} 行，本次 {total} 行：應判 Tier 1")
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "summary": args.summary,
        "files": files,
        "lines": total,
        "lines_verified": True,
        "per_file_lines": per_file,
        "mechanical": bool(args.mechanical),
    }
    os.makedirs("run", exist_ok=True)
    with open(TIER0_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[eval-state] tier0 留痕 +1 -> {TIER0_LOG}")


def cmd_archive(args):
    state = load()
    run_id = state.get("run_id")
    if not run_id:
        fail("缺 run_id，無法歸檔", code=2)
    if not state.get("sub_tasks"):
        fail("sub_tasks 為空，無可歸檔內容", code=2)
    eval_gates.validate_state(state, STATE_PATH, require_passed=True)  # 不過 → exit 2
    archive_path = f"run/{run_id}.eval.json"
    os.makedirs("run", exist_ok=True)
    save(state, archive_path)
    append_event(run_id, "archive", args)
    os.remove(STATE_PATH)
    print(f"[eval-state] 已歸檔 {archive_path} 並清除 {STATE_PATH}（記得把 manifest 標 completed）")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.add_argument("--run-id", required=True)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add-subtask")
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_add_subtask)

    p = sub.add_parser("set-step")
    p.add_argument("id", type=int)
    p.add_argument("step", choices=STEPS)
    p.set_defaults(func=cmd_set_step)

    p = sub.add_parser("set-files")
    p.add_argument("id", type=int)
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_set_files)

    p = sub.add_parser("set-test")
    p.add_argument("id", type=int)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--passed", action="store_true")
    g.add_argument("--failed", action="store_true")
    p.add_argument("--evidence")
    p.set_defaults(func=cmd_set_test)

    p = sub.add_parser("set-status")
    p.add_argument("id", type=int)
    p.add_argument("status", choices=STATUSES)
    p.add_argument("--warning", action="store_true")
    p.set_defaults(func=cmd_set_status)

    p = sub.add_parser("set-review")
    p.add_argument("id", type=int)
    p.add_argument("reds", type=int)
    p.add_argument("--dimensions", default=None,
                   help="維度→問題數 JSON，如 '{\"Clarity\":1}'")
    p.add_argument("--checked-by", dest="checked_by", default=None,
                   help="審定者留痕：checker｜reviewer:①-⑤｜reviewer:manual｜reviewer:boundary")
    p.set_defaults(func=cmd_set_review)

    p = sub.add_parser("set-verify")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_set_verify)

    p = sub.add_parser("add-verification")
    p.add_argument("id", type=int)
    p.add_argument("--command", required=True)
    p.add_argument("--exit-code", type=int, required=True, dest="exit_code")
    p.set_defaults(func=cmd_add_verification)

    p = sub.add_parser("event")
    p.add_argument("run_id")
    p.add_argument("name")
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_event)

    p = sub.add_parser("hitl-confirm")
    p.add_argument("run_id")
    p.add_argument("--note", required=True, help="確認範圍一句話（寫入 hitl_confirmed_at）")
    p.add_argument("--rulings", type=int, default=0, help="使用者裁示條數（預設 0）")
    p.set_defaults(func=cmd_hitl_confirm)

    p = sub.add_parser("tier0")
    p.add_argument("--summary", required=True)
    p.add_argument("--files", required=True, help="逗號分隔的檔案清單")
    p.add_argument("--lines", type=int, required=True,
                   help="自報的變更行數（增＋刪）；與 git diff 實得不符即拒絕留痕")
    p.add_argument("--mechanical", action="store_true",
                   help="同一種機械式改動跨多檔（CLAUDE.md 例外）：不限檔數，但每檔 ≤50 行")
    p.set_defaults(func=cmd_tier0)

    p = sub.add_parser("list-files")
    p.set_defaults(func=cmd_list_files)

    p = sub.add_parser("archive")
    p.set_defaults(func=cmd_archive)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
