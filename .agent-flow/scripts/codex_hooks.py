"""Read native hook trust before shared Codex dispatch; never create approvals."""

import json
import os
import select
import shlex
import subprocess
import tempfile
import time


def require_trusted(argv, hooks):
    """Use the same CLI's read-only catalog, without starting a model or a thread."""
    overrides = []
    for index, value in enumerate(argv):
        if value == "-c":
            overrides.extend(argv[index : index + 2])
    expected = {event[0].lower() + event[1:] for event in hooks}
    count = sum(len(group["hooks"]) for groups in hooks.values() for group in groups)
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            [argv[0], "app-server", "--stdio", *overrides],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
        )
        try:
            requests = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {"name": "agent-flow-hook-check", "version": "1"},
                        "capabilities": {"experimentalApi": True},
                    },
                },
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "hooks/list",
                    "params": {"cwds": [os.getcwd()]},
                },
            ]
            process.stdin.write(
                ("\n".join(json.dumps(r) for r in requests) + "\n").encode()
            )
            process.stdin.flush()
            pending = b""
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if not select.select(
                    [process.stdout], [], [], max(0, deadline - time.monotonic())
                )[0]:
                    break
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    response = json.loads(line)
                    if not isinstance(response, dict):
                        raise ValueError(
                            "Codex hook inventory response must be an object; child not started"
                        )
                    if response.get("id") != 2:
                        continue
                    if "error" in response:
                        raise ValueError(
                            "Codex hooks/list unavailable; shared dispatch cannot confirm hook trust"
                        )
                    # This is the untrusted client-response boundary. Missing or
                    # changed schema raises a controlled error before any model starts.
                    entries = response["result"]["data"]
                    injected = [
                        h
                        for entry in entries
                        for h in entry["hooks"]
                        if h["source"] == "sessionFlags"
                    ]
                    if (
                        len(injected) == count
                        and {h["eventName"] for h in injected} == expected
                        and all(
                            h["enabled"] is True and h["trustStatus"] == "trusted"
                            for h in injected
                        )
                    ):
                        return
                    definitions = "\n".join(
                        f"{h['eventName']}: enabled={h['enabled']}, trust={h['trustStatus']}, "
                        f"hash={h['currentHash']}\n  command: {h['command']}"
                        for h in injected
                    )
                    interactive = shlex.join([argv[0], "-C", os.getcwd(), *overrides])
                    raise ValueError(
                        "Codex 共享派工的注入 hooks 未啟用或未受信任；未啟動子 agent。"
                        "dispatch 不會建立批准或略過 hook trust。\n"
                        + definitions
                        + "\n正常審閱入口（保留既有權限，先核對下列精確定義）：\n"
                        + interactive
                        + "\n在 /hooks 逐項選取上述 SessionFlags handler，核對 command/hash 後"
                        "由使用者正常信任；不要 trust-all。未啟用者須由使用者核對原因。"
                        "定義變更後須重新審閱；不可沿用舊 hash。完成後可直接重試同一派工，"
                        "不必重建 run。同一穩定工具鏈在不同目標使用相同定義，可沿用正常信任。"
                    )
            raise ValueError(
                "Codex hook inventory unavailable or timed out after 15s; child not started"
            )
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(
                "Codex hook inventory schema is unsupported; child not started"
            ) from error
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            process.stdin.close()
            process.stdout.close()
