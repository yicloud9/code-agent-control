# Hooks For Coding-Agent Telemetry

Use hooks only when the user wants persistent telemetry beyond normal controller status, such as an append-only project event log.

## Claude Code

Create a fast project-local hook that reads JSON from stdin and appends events to a local JSONL file. Configure it in `.claude/settings.json` for the events relevant to the request, such as `SessionStart`, `PermissionRequest`, `TaskCreated`, `TaskCompleted`, `Stop`, `StopFailure`, and `SessionEnd`.

For normal polling, still prefer `claude agents --json --all`. It exposes live background-session state and `waitingFor`; hooks are the durable audit trail.

## Kimi Code

Kimi hooks live in `~/.kimi-code/config.toml` as `[[hooks]]` entries. Each rule accepts only `event`, optional `matcher`, `command`, and optional `timeout`.

Example completion notification:

```toml
[[hooks]]
event = "Notification"
matcher = "task\\.completed"
command = "python3 /absolute/path/to/kimi-event-log.py"
timeout = 10
```

The command receives snake_case JSON on stdin, including baseline fields such as `hook_event_name`, `session_id`, and `cwd`. Use a logger like this:

```python
#!/usr/bin/env python3
import json
import pathlib
import sys
import time

event = json.load(sys.stdin)
root = pathlib.Path(event.get("cwd", "."))
log_dir = root / ".kimi-code" / "control"
log_dir.mkdir(parents=True, exist_ok=True)
payload = {
    "ts": time.time(),
    "event": event.get("hook_event_name"),
    "session_id": event.get("session_id"),
    "cwd": event.get("cwd"),
    "raw": event,
}
with (log_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
```

Kimi hook exit code `0` allows the action, `2` blocks it, and other codes fail open. Do not use hooks as the only defense for high-risk operations.

For normal Kimi managed-job polling, still prefer `code_agent_control.py status`; it reads the wrapper's process and exit state. Kimi hooks record Kimi-side events and complement that state.

## Shared Guidance

- Keep hooks append-only and fast.
- Avoid secrets and large raw payloads in logs.
- Use absolute script paths in hook configuration.
- Do not let telemetry hooks make permission decisions unless the user asks for policy enforcement.
