#!/usr/bin/env python3
"""Record confirmed items and their delivery evidence in a run manifest."""

import argparse
import datetime
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import sys

from flow_rules import RuleViolation, plan_timestamp, requires_item_accounting


def require(condition, message):
    if not condition:
        raise RuleViolation(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def parse_items(task_text):
    """Checkbox state is deliberately excluded from the confirmed identity."""
    items = []
    task_id = None
    for line in task_text.splitlines():
        heading = re.match(r"^##\s+Task\s+(\d+)\s*[:：]", line)
        if heading:
            task_id = heading.group(1)
        match = re.match(r"^\s*-\s+\[[ xX]\]\s+(\d+\.\d+)\s+(.+?)\s*$", line)
        if match:
            item_id, summary = match.groups()
            require(task_id == item_id.split(".")[0], f"item {item_id} task 不符")
            require(
                not any(item["id"] == item_id for item in items), f"重複 item {item_id}"
            )
            items.append(dict(id=item_id, task_id=task_id, summary=summary))
    require(bool(items), "item 清單不可為空")
    return items


def confirm_plan(manifest, task_text):
    require(requires_item_accounting(manifest), "舊 run 不補造 item 清單")
    require(nonempty(plan_timestamp(manifest)), "先完成 HITL 確認")
    require("item_plan" not in manifest, "item 計畫已確認，不可覆寫")
    manifest["item_plan"] = {
        "confirmed_at": plan_timestamp(manifest),
        "items": parse_items(task_text),
    }
    manifest["item_results"] = {}


def validate_plan(manifest, task_text):
    plan = manifest.get("item_plan")
    require(isinstance(plan, dict), "缺 item_plan：先執行 confirm-plan")
    require(nonempty(plan_timestamp(manifest)), "先完成 HITL 確認")
    require(plan.get("confirmed_at") == plan_timestamp(manifest), "item 確認時間不符")
    require(plan.get("items") == parse_items(task_text), "task item 與確認清單不符")
    return plan["items"]


def validate_ruling(ruling):
    require(isinstance(ruling, dict), "缺使用者裁示")
    require(ruling.get("actor") == "user", "只有使用者可裁示移除")
    for key in ("text", "at", "source"):
        require(nonempty(ruling.get(key)), f"裁示缺 {key}")
    try:
        timestamp = datetime.datetime.fromisoformat(ruling["at"].replace("Z", "+00:00"))
        require(timestamp.tzinfo is not None, "裁示時間須含時區")
    except ValueError as error:
        raise RuleViolation("裁示時間須為 ISO 8601") from error
    require(
        not ruling["source"].strip().casefold().startswith(("agent", "assistant")),
        "agent 建議不是使用者裁示",
    )


def validate_files(files):
    require(isinstance(files, list) and bool(files), "交付 files 不可為空")
    require(all(nonempty(path) for path in files), "交付檔案路徑不可為空")
    require(len(files) == len(set(files)), "交付檔案路徑重複")
    for path in files:
        parsed = PurePosixPath(path)
        require(
            not parsed.is_absolute()
            and ".." not in parsed.parts
            and str(parsed) == path
            and path != ".",
            "交付須用專案相對檔案路徑",
        )


def record_partial(manifest, task_text, item_ids, ruling):
    validate_plan(manifest, task_text)
    validate_ruling(ruling)
    require(manifest.get("status") in ("in_progress", "paused"), "run 已收尾")
    unresolved = validate_results(manifest, allow_pending=True)
    require(isinstance(item_ids, list) and bool(item_ids), "partial 清單不可為空")
    require(
        len(item_ids) == len(set(item_ids)) and sorted(item_ids) == unresolved,
        "partial 清單須等於全部未交付 item",
    )
    manifest["partial_acceptance"] = dict(item_ids=sorted(item_ids), ruling=ruling)
    manifest["status"] = "in_progress"


def validate_results(manifest, files=None, allow_pending=False):
    """Pure validation; callers supply staged or actual commit paths."""
    plan = manifest.get("item_plan")
    require(
        isinstance(plan, dict)
        and isinstance(plan.get("items"), list)
        and bool(plan["items"]),
        "缺 item_plan",
    )
    results = manifest.get("item_results")
    require(isinstance(results, dict), "缺 item_results")
    require(
        nonempty(plan_timestamp(manifest))
        and plan.get("confirmed_at") == plan_timestamp(manifest),
        "item 確認資料不符",
    )
    for item in plan["items"]:
        require(
            isinstance(item, dict)
            and all(nonempty(item.get(key)) for key in ("id", "task_id", "summary")),
            "item 計畫格式錯誤",
        )
    ids = {item["id"] for item in plan["items"]}
    require(len(ids) == len(plan["items"]), "item 計畫包含重複 ID")
    require(set(results) <= ids, "結果包含未確認 item")
    unresolved = []
    for item_id in ids:
        result = results.get(item_id, {})
        require(isinstance(result, dict), f"item {item_id} 結果格式錯誤")
        status = result.get("status")
        if status == "delivered":
            validate_files(result.get("files"))
            if files is not None:
                require(
                    set(result["files"]) <= set(files),
                    f"item {item_id} 交付檔案不在本次提交",
                )
        elif status == "removed":
            validate_ruling(result.get("ruling"))
        else:
            require(status in (None, "pending"), f"item {item_id} 狀態錯誤")
            if status == "pending":
                require(nonempty(result.get("reason")), f"item {item_id} 缺待裁示理由")
            unresolved.append(item_id)
    require(
        allow_pending or not unresolved, f"未結清 item：{', '.join(sorted(unresolved))}"
    )
    return sorted(unresolved)


def record_result(
    manifest, task_text, item_id, status, *, files=None, reason=None, ruling=None
):
    items = validate_plan(manifest, task_text)
    require(item_id in {item["id"] for item in items}, "未確認的 item")
    require(manifest.get("status") in ("in_progress", "paused"), "run 已收尾")
    if status == "delivered":
        validate_files(files)
        result = dict(status=status, files=files)
    elif status == "pending":
        require(nonempty(reason), "待裁示理由不可為空")
        result = dict(status=status, reason=reason)
    elif status == "removed":
        validate_ruling(ruling)
        result = dict(status=status, ruling=ruling)
    else:
        raise RuleViolation("不支援的 item 狀態")
    results = manifest.get("item_results")
    require(isinstance(results, dict), "缺 item_results")
    require(results.get(item_id, {}).get("status") != "removed", "已裁示移除，不可覆寫")
    was_pending = results.get(item_id, {}).get("status") == "pending"
    results[item_id] = result
    if status == "pending":
        manifest["status"] = "paused"
    elif was_pending and not any(
        record.get("status") == "pending" for record in results.values()
    ):
        manifest["status"] = "in_progress"


LOGGER = logging.getLogger(__name__)


class DiagnosticFormatter(logging.Formatter):
    def __init__(self, output_format):
        super().__init__()
        self.output_format = output_format

    def format(self, record):
        fields = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created, datetime.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.event,
            "message": record.getMessage(),
        }
        for key in ("run_id", "outcome", "reason", "exit_code"):
            value = getattr(record, key, None)
            if value is not None:
                fields[key] = value
        if self.output_format == "json":
            return json.dumps(fields, ensure_ascii=False)
        return " ".join(
            f"{key}={json.dumps(value, ensure_ascii=False)}"
            for key, value in fields.items()
        )


class InputParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def configure_logging(level="INFO", output_format="text"):
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(DiagnosticFormatter(output_format))
    LOGGER.handlers = [handler]
    LOGGER.setLevel(level)
    LOGGER.propagate = False


def main():
    log_options = InputParser(add_help=False)
    log_options.add_argument(
        "--log-level",
        type=str.upper,
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=argparse.SUPPRESS,
    )
    log_options.add_argument(
        "--log-format", choices=("text", "json"), default=argparse.SUPPRESS
    )
    parser = InputParser(description=__doc__, parents=[log_options])
    parser.add_argument("--run-id", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("confirm-plan", parents=[log_options])
    deliver = commands.add_parser("deliver", parents=[log_options])
    deliver.add_argument("item_id")
    deliver.add_argument("--files", nargs="+", required=True)
    pending = commands.add_parser("pending", parents=[log_options])
    pending.add_argument("item_id")
    pending.add_argument("--reason", required=True)
    remove = commands.add_parser("remove", parents=[log_options])
    remove.add_argument("item_id")
    remove.add_argument(
        "--ruling-file", required=True, help="JSON: actor=user, text, at, source"
    )
    partial = commands.add_parser("partial", parents=[log_options])
    partial.add_argument("--items", nargs="+", required=True)
    partial.add_argument("--ruling-file", required=True)
    configure_logging()
    args = None
    try:
        options, _ = log_options.parse_known_args()
        configure_logging(
            getattr(options, "log_level", "INFO"),
            getattr(options, "log_format", "text"),
        )
        args = parser.parse_args()
        require(
            bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.run_id)),
            "run_id 格式錯誤",
        )
        manifest_path = Path("run") / f"{args.run_id}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        task_text = Path(manifest["task_file"]).read_text(encoding="utf-8")
        if args.command == "confirm-plan":
            confirm_plan(manifest, task_text)
        else:
            ruling = None
            if args.command in ("remove", "partial"):
                require(
                    os.environ.get("CLAUDE_CODE_SESSION_ATTENDED")
                    not in ("0", "false", "False"),
                    "無人看管的 session 不得記使用者裁示",
                )
                ruling = json.loads(Path(args.ruling_file).read_text(encoding="utf-8"))
            if args.command == "partial":
                record_partial(manifest, task_text, args.items, ruling)
            else:
                record_result(
                    manifest,
                    task_text,
                    args.item_id,
                    {"deliver": "delivered", "pending": "pending", "remove": "removed"}[
                        args.command
                    ],
                    files=getattr(args, "files", None),
                    reason=getattr(args, "reason", None),
                    ruling=ruling,
                )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        LOGGER.info(
            "item 記錄已更新",
            extra=dict(
                event="item_accounting.recorded",
                run_id=args.run_id,
                outcome="recorded",
                exit_code=0,
            ),
        )
    except (RuleViolation, OSError, ValueError, KeyError, TypeError) as error:
        blocked = isinstance(error, (RuleViolation, ValueError))
        LOGGER.log(
            logging.INFO if blocked else logging.ERROR,
            str(error),
            extra=dict(
                event=(
                    "item_accounting.blocked" if blocked else "item_accounting.failed"
                ),
                run_id=getattr(args, "run_id", None),
                outcome="blocked" if blocked else "failed",
                reason="invalid_input" if blocked else "operation_failed",
                exit_code=2,
            ),
        )
        parser.exit(2)


if __name__ == "__main__":
    main()
