#!/usr/bin/env python3
"""Control Claude Code sessions and managed Kimi Code background jobs."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


SKILL_NAME = "code-agent-control"
ACTIVE_STATES = {"queued", "working"}
TERMINAL_STATES = {"done", "failed", "stopped"}
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CLAUDE_JOB_ID_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{8})(?![0-9A-Fa-f])")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(
    args: List[str], cwd: Optional[str] = None, check: bool = True
) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


def emit(payload: Any) -> None:
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


def require_cli(name: str) -> str:
    located = shutil.which(name)
    if located:
        return located
    standard_paths = {
        "kimi": Path.home() / ".kimi-code" / "bin" / "kimi",
        "claude": Path.home() / ".local" / "bin" / "claude",
    }
    candidate = standard_paths.get(name)
    if candidate and candidate.is_file() and os.access(str(candidate), os.X_OK):
        return str(candidate)
    raise RuntimeError(
        "%s CLI was not found on PATH or in its standard user install location. "
        "Install and authenticate it before dispatching work." % name
    )


def kimi_config_path() -> Path:
    configured_home = os.environ.get("KIMI_CODE_HOME")
    if configured_home:
        return Path(configured_home).expanduser() / "config.toml"
    return Path.home() / ".kimi-code" / "config.toml"


def kimi_model_aliases() -> List[tuple]:
    """Return configured (alias, provider model id) pairs without reading secrets."""
    path = kimi_config_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    section_pattern = re.compile(r'^\[models\.(?:"([^"]+)"|([^\]]+))\]\s*$')
    value_pattern = re.compile(r'^model\s*=\s*["\']([^"\']+)["\']\s*$')
    aliases = []
    current_alias = None
    for line in lines:
        stripped = line.strip()
        section = section_pattern.match(stripped)
        if section:
            current_alias = section.group(1) or section.group(2).strip()
            continue
        if current_alias:
            value = value_pattern.match(stripped)
            if value:
                aliases.append((current_alias, value.group(1)))
                current_alias = None
    return aliases


def resolve_kimi_model(requested: Optional[str]) -> Optional[str]:
    """Resolve a provider model id to the alias registered in Kimi config.toml."""
    if not requested:
        return None

    configured = kimi_model_aliases()
    aliases = {alias for alias, _ in configured}
    if requested in aliases:
        return requested

    matching_aliases = [alias for alias, model_id in configured if model_id == requested]
    if len(matching_aliases) == 1:
        return matching_aliases[0]
    if len(matching_aliases) > 1:
        raise ValueError(
            "Kimi model id %r maps to multiple configured aliases: %s"
            % (requested, ", ".join(matching_aliases))
        )

    if configured:
        available = ", ".join(alias for alias, _ in configured)
        raise ValueError(
            "Kimi model %r is not registered in %s. Use a configured alias: %s"
            % (requested, kimi_config_path(), available)
        )
    # If a nonstandard KIMI_CODE_HOME is unavailable, preserve an explicit
    # alias and let Kimi provide its own authentication/configuration error.
    return requested


def parse_claude_agents(raw: str) -> List[Dict[str, Any]]:
    if not raw.strip():
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("claude agents --json did not return a JSON array")
    return data


def extract_claude_job_id(output: str) -> Optional[str]:
    """Extract a Claude background job id from colored or mixed CLI output."""
    clean_output = ANSI_ESCAPE_RE.sub("", output)
    match = CLAUDE_JOB_ID_RE.search(clean_output)
    return match.group(1).lower() if match else None


def control_home() -> Path:
    configured = os.environ.get("CODE_AGENT_CONTROL_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex" / SKILL_NAME


def kimi_jobs_dir() -> Path:
    return control_home() / "kimi-jobs"


def kimi_job_dir(job_id: str) -> Path:
    if not job_id.startswith("kimi-") or any(part in job_id for part in ("/", "\\", "..")):
        raise ValueError("invalid Kimi job id: %s" % job_id)
    return kimi_jobs_dir() / job_id


def kimi_state_path(job_id: str) -> Path:
    return kimi_job_dir(job_id) / "state.json"


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, str(path))
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def read_kimi_state(job_id: str) -> Dict[str, Any]:
    path = kimi_state_path(job_id)
    if not path.exists():
        raise FileNotFoundError("Kimi job not found: %s" % job_id)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("invalid state file for %s" % job_id)
    return data


def process_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def refresh_kimi_state(job_id: str) -> Dict[str, Any]:
    state = read_kimi_state(job_id)
    if state.get("state") in ACTIVE_STATES and not process_alive(state.get("workerPid")):
        time.sleep(0.05)
        state = read_kimi_state(job_id)
        if state.get("state") in ACTIVE_STATES and not process_alive(state.get("workerPid")):
            state.update(
                {
                    "state": "failed",
                    "completedAt": now_iso(),
                    "error": "Kimi worker exited without recording a terminal state.",
                }
            )
            write_json_atomic(kimi_state_path(job_id), state)
    return state


def public_kimi_state(state: Dict[str, Any]) -> Dict[str, Any]:
    hidden = {"prompt", "command"}
    result = {key: value for key, value in state.items() if key not in hidden}
    result["statusSource"] = "managed-local-process"
    return result


def list_kimi_states(cwd: Optional[str], include_all: bool) -> List[Dict[str, Any]]:
    root = kimi_jobs_dir()
    if not root.exists():
        return []
    requested_cwd = str(Path(cwd).expanduser().resolve()) if cwd else None
    jobs = []
    for path in root.iterdir():
        if not path.is_dir() or not path.name.startswith("kimi-"):
            continue
        try:
            state = refresh_kimi_state(path.name)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if requested_cwd and state.get("cwd") != requested_cwd:
            continue
        if not include_all and state.get("state") not in ACTIVE_STATES:
            continue
        jobs.append(public_kimi_state(state))
    jobs.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
    return jobs


def claude_list(cwd: Optional[str], include_all: bool) -> List[Dict[str, Any]]:
    claude_cli = require_cli("claude")
    cmd = [claude_cli, "agents", "--json"]
    if include_all:
        cmd.append("--all")
    if cwd:
        cmd.extend(["--cwd", cwd])
    return parse_claude_agents(run(cmd).stdout)


def discover_claude_job_id(
    cwd: str, name: Optional[str], started_after_ms: Optional[int]
) -> Optional[str]:
    """Find a newly-created Claude background job when dispatch output has no id."""
    try:
        sessions = claude_list(cwd, True)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError, json.JSONDecodeError):
        return None

    candidates = []
    for session in sessions:
        if session.get("kind") != "background":
            continue
        if str(session.get("cwd", "")) != cwd:
            continue
        if name and session.get("name") != name:
            continue
        started_at = session.get("startedAt")
        if started_after_ms is not None and isinstance(started_at, (int, float)):
            if started_at < started_after_ms - 2000:
                continue
        job_id = str(session.get("id", ""))
        if CLAUDE_JOB_ID_RE.fullmatch(job_id):
            sort_started_at = started_at if isinstance(started_at, (int, float)) else 0
            candidates.append((sort_started_at, job_id.lower()))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def cmd_list(args: argparse.Namespace) -> int:
    if args.backend == "claude":
        emit({"backend": "claude", "jobs": claude_list(args.cwd, args.all)})
        return 0
    if args.backend == "kimi":
        emit({"backend": "kimi", "jobs": list_kimi_states(args.cwd, args.all)})
        return 0

    payload: Dict[str, Any] = {"backend": "all"}
    try:
        payload["claude"] = claude_list(args.cwd, args.all)
    except Exception as exc:
        payload["claudeError"] = str(exc)
    payload["kimi"] = list_kimi_states(args.cwd, args.all)
    emit(payload)
    return 0


def inferred_backend(job_id: str, requested: str) -> str:
    if requested != "auto":
        return requested
    return "kimi" if job_id.startswith("kimi-") else "claude"


def cmd_status(args: argparse.Namespace) -> int:
    backend = inferred_backend(args.id, args.backend)
    if backend == "kimi":
        emit(public_kimi_state(refresh_kimi_state(args.id)))
        return 0

    sessions = claude_list(args.cwd, True)
    matches = [
        item
        for item in sessions
        if args.id
        in {
            str(item.get("id", "")),
            str(item.get("sessionId", "")),
            str(item.get("pid", "")),
        }
    ]
    if not matches:
        emit(
            {
                "backend": "claude",
                "found": False,
                "id": args.id,
                "sessions": sessions if args.include_all else [],
            }
        )
        return 1
    emit({"backend": "claude", "found": True, "matches": matches})
    return 0


def tail_text(path: Path, line_count: int) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return "".join(lines[-line_count:]).rstrip()


def cmd_logs(args: argparse.Namespace) -> int:
    backend = inferred_backend(args.id, args.backend)
    if backend == "claude":
        claude_cli = require_cli("claude")
        emit(run([claude_cli, "logs", args.id]).stdout.rstrip())
        return 0

    state = refresh_kimi_state(args.id)
    job_dir = kimi_job_dir(args.id)
    emit(
        {
            "backend": "kimi",
            "id": args.id,
            "state": state.get("state"),
            "stdout": tail_text(job_dir / "stdout.log", args.tail),
            "stderr": tail_text(job_dir / "stderr.log", args.tail),
        }
    )
    return 0


def claude_dispatch(args: argparse.Namespace) -> int:
    claude_cli = require_cli("claude")
    cwd = str(Path(args.cwd).expanduser().resolve())
    dispatch_started_ms = int(time.time() * 1000)
    cmd = [claude_cli, "--bg"]
    settings_file = None
    if args.name:
        cmd.extend(["--name", args.name])
    if args.model:
        cmd.extend(["--model", args.model])
    if args.effort:
        cmd.extend(["--effort", args.effort])
    cmd.extend(["--permission-mode", args.permission_mode or "auto"])
    for extra_dir in args.add_dir:
        cmd.extend(["--add-dir", extra_dir])
    if args.use_current_anthropic_env:
        env_keys = [
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_SMALL_FAST_MODEL",
        ]
        env = {key: os.environ[key] for key in env_keys if os.environ.get(key)}
        if not env:
            raise ValueError(
                "--use-current-anthropic-env was set, but no supported ANTHROPIC_* env vars were present"
            )
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix="code-agent-control-settings-",
            suffix=".json",
            delete=False,
        ) as handle:
            json.dump({"env": env}, handle)
            settings_file = handle.name
        cmd.extend(["--settings", settings_file])
    if args.dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd.append(args.prompt)
    try:
        result = run(cmd, cwd=cwd)
        dispatch_output = "\n".join(
            part for part in (result.stdout, result.stderr) if part
        )
        emit(ANSI_ESCAPE_RE.sub("", dispatch_output).rstrip())
        if settings_file:
            # Claude normally prints the job id to stdout, but terminal color
            # settings and CLI warnings can move it to stderr.  Parse both
            # streams so the temporary settings file is not removed before the
            # detached worker has initialized.
            wait_for_claude_settings_read(
                dispatch_output,
                args.settings_keepalive_seconds,
                cwd=cwd,
                name=args.name,
                started_after_ms=dispatch_started_ms,
            )
        return 0
    finally:
        if settings_file:
            try:
                os.unlink(settings_file)
            except FileNotFoundError:
                pass


def wait_for_claude_settings_read(
    dispatch_output: str,
    timeout_seconds: float,
    cwd: Optional[str] = None,
    name: Optional[str] = None,
    started_after_ms: Optional[int] = None,
) -> None:
    job_id = extract_claude_job_id(dispatch_output)
    deadline = time.monotonic() + timeout_seconds
    if not job_id:
        while cwd and time.monotonic() < deadline:
            job_id = discover_claude_job_id(cwd, name, started_after_ms)
            if job_id:
                break
            time.sleep(0.25)
        if not job_id:
            return

    state_path = Path.home() / ".claude" / "jobs" / job_id / "state.json"
    while time.monotonic() < deadline:
        try:
            with state_path.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.25)
            continue
        detail = str(state.get("detail", ""))
        if "Settings file not found" in detail:
            return
        if (
            state.get("cliVersion")
            or state.get("firstTerminalAt")
            or state.get("state") in TERMINAL_STATES
        ):
            return
        time.sleep(0.25)


def validate_kimi_dispatch(args: argparse.Namespace) -> None:
    unsupported = []
    if args.effort:
        unsupported.append("--effort")
    if args.use_current_anthropic_env:
        unsupported.append("--use-current-anthropic-env")
    if args.dangerously_skip_permissions:
        unsupported.append("--dangerously-skip-permissions")
    if args.permission_mode and args.permission_mode != "auto":
        unsupported.append("--permission-mode %s" % args.permission_mode)
    if unsupported:
        raise ValueError(
            "Kimi -p does not support these Claude-only options: %s"
            % ", ".join(unsupported)
        )
    if args.continue_session and args.session:
        raise ValueError("--continue and --session are mutually exclusive")


def make_kimi_command(args: argparse.Namespace) -> List[str]:
    cmd = [require_cli("kimi")]
    if args.continue_session:
        cmd.append("--continue")
    if args.session:
        cmd.extend(["--session", args.session])
    if args.model:
        cmd.extend(["--model", args.model])
    for extra_dir in args.add_dir:
        cmd.extend(["--add-dir", extra_dir])
    cmd.extend(["--prompt", args.prompt, "--output-format", args.output_format])
    return cmd


def start_kimi_job(state: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str(state["id"])
    write_json_atomic(kimi_state_path(job_id), state)
    worker = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "_run-kimi-job", job_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    state["workerPid"] = worker.pid
    write_json_atomic(kimi_state_path(job_id), state)
    return state


def kimi_dispatch(args: argparse.Namespace, respawn_of: Optional[str] = None) -> int:
    require_cli("kimi")
    validate_kimi_dispatch(args)
    requested_model = args.model
    args.model = resolve_kimi_model(args.model)
    cwd_path = Path(args.cwd).expanduser().resolve()
    if not cwd_path.is_dir():
        raise ValueError("working directory does not exist: %s" % cwd_path)
    job_id = "kimi-%s-%s" % (
        datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        uuid.uuid4().hex[:8],
    )
    job_dir = kimi_job_dir(job_id)
    state: Dict[str, Any] = {
        "id": job_id,
        "backend": "kimi",
        "name": args.name,
        "state": "queued",
        "cwd": str(cwd_path),
        "prompt": args.prompt,
        "command": make_kimi_command(args),
        "model": args.model,
        "requestedModel": requested_model if requested_model != args.model else None,
        "session": args.session,
        "continue": bool(args.continue_session),
        "outputFormat": args.output_format,
        "addDir": list(args.add_dir),
        "createdAt": now_iso(),
        "startedAt": None,
        "completedAt": None,
        "exitCode": None,
        "workerPid": None,
        "stdoutLog": str(job_dir / "stdout.log"),
        "stderrLog": str(job_dir / "stderr.log"),
    }
    if respawn_of:
        state["respawnOf"] = respawn_of
    start_kimi_job(state)
    emit(public_kimi_state(state))
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    if args.backend == "claude":
        if args.session or args.continue_session or args.output_format != "text":
            raise ValueError("--session, --continue, and --output-format are Kimi-only dispatch options")
        return claude_dispatch(args)
    return kimi_dispatch(args)


def worker_run_kimi_job(job_id: str) -> int:
    state_path = kimi_state_path(job_id)
    deadline = time.monotonic() + 5
    state = read_kimi_state(job_id)
    while state.get("workerPid") is None and time.monotonic() < deadline:
        time.sleep(0.02)
        state = read_kimi_state(job_id)
    state.update({"state": "working", "startedAt": now_iso()})
    write_json_atomic(state_path, state)
    job_dir = kimi_job_dir(job_id)
    try:
        with (job_dir / "stdout.log").open("a", encoding="utf-8") as stdout_handle, (
            job_dir / "stderr.log"
        ).open("a", encoding="utf-8") as stderr_handle:
            result = subprocess.run(
                list(state["command"]),
                cwd=str(state["cwd"]),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                check=False,
            )
        state = read_kimi_state(job_id)
        if state.get("state") == "stopped":
            return 0
        state.update(
            {
                "state": "done" if result.returncode == 0 else "failed",
                "exitCode": result.returncode,
                "completedAt": now_iso(),
            }
        )
        write_json_atomic(state_path, state)
        return result.returncode
    except Exception as exc:
        state = read_kimi_state(job_id)
        if state.get("state") != "stopped":
            state.update(
                {
                    "state": "failed",
                    "completedAt": now_iso(),
                    "error": str(exc),
                }
            )
            write_json_atomic(state_path, state)
        return 1


def cmd_stop(args: argparse.Namespace) -> int:
    backend = inferred_backend(args.id, args.backend)
    if backend == "claude":
        claude_cli = require_cli("claude")
        emit(run([claude_cli, "stop", args.id]).stdout.rstrip())
        return 0

    state = refresh_kimi_state(args.id)
    if state.get("state") not in ACTIVE_STATES:
        raise ValueError("Kimi job %s is already %s" % (args.id, state.get("state")))
    pid = state.get("workerPid")
    if process_alive(pid):
        try:
            os.killpg(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + args.timeout
        while process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if process_alive(pid):
            os.killpg(int(pid), signal.SIGKILL)
    state.update({"state": "stopped", "completedAt": now_iso(), "exitCode": None})
    write_json_atomic(kimi_state_path(args.id), state)
    emit(public_kimi_state(state))
    return 0


def args_from_kimi_state(state: Dict[str, Any]) -> argparse.Namespace:
    return argparse.Namespace(
        backend="kimi",
        cwd=state["cwd"],
        prompt=state["prompt"],
        name=state.get("name"),
        model=state.get("model"),
        effort=None,
        permission_mode=None,
        add_dir=state.get("addDir", []),
        use_current_anthropic_env=False,
        settings_keepalive_seconds=20,
        dangerously_skip_permissions=False,
        session=state.get("session"),
        continue_session=bool(state.get("continue")),
        output_format=state.get("outputFormat", "text"),
    )


def cmd_respawn(args: argparse.Namespace) -> int:
    backend = inferred_backend(args.id, args.backend)
    if backend == "claude":
        claude_cli = require_cli("claude")
        emit(run([claude_cli, "respawn", args.id]).stdout.rstrip())
        return 0

    state = refresh_kimi_state(args.id)
    if state.get("state") in ACTIVE_STATES:
        raise ValueError("stop the active Kimi job before respawning it")
    return kimi_dispatch(args_from_kimi_state(state), respawn_of=args.id)


def cmd_rm(args: argparse.Namespace) -> int:
    backend = inferred_backend(args.id, args.backend)
    if backend == "claude":
        claude_cli = require_cli("claude")
        emit(run([claude_cli, "rm", args.id]).stdout.rstrip())
        return 0

    state = refresh_kimi_state(args.id)
    if state.get("state") in ACTIVE_STATES:
        raise ValueError("stop the active Kimi job before removing it")
    shutil.rmtree(kimi_job_dir(args.id))
    emit({"backend": "kimi", "removed": True, "id": args.id})
    return 0


def add_backend_argument(parser: argparse.ArgumentParser, choices: List[str], default: str) -> None:
    parser.add_argument("--backend", choices=choices, default=default)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Control Claude Code sessions and managed Kimi Code background jobs."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List Claude sessions and/or Kimi jobs.")
    add_backend_argument(p_list, ["all", "claude", "kimi"], "all")
    p_list.add_argument("--cwd", help="Filter jobs by working directory.")
    p_list.add_argument("--all", action="store_true", help="Include completed jobs.")
    p_list.set_defaults(func=cmd_list)

    p_status = sub.add_parser("status", help="Inspect one job.")
    p_status.add_argument("id")
    add_backend_argument(p_status, ["auto", "claude", "kimi"], "auto")
    p_status.add_argument("--cwd", help="Filter Claude sessions by working directory.")
    p_status.add_argument("--include-all", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_logs = sub.add_parser("logs", help="Print recent output for a job.")
    p_logs.add_argument("id")
    add_backend_argument(p_logs, ["auto", "claude", "kimi"], "auto")
    p_logs.add_argument("--tail", type=int, default=200, help="Lines per Kimi log stream.")
    p_logs.set_defaults(func=cmd_logs)

    p_dispatch = sub.add_parser("dispatch", help="Start a Claude or Kimi task.")
    add_backend_argument(p_dispatch, ["claude", "kimi"], None)
    p_dispatch.add_argument("--cwd", required=True, help="Project directory for the task.")
    p_dispatch.add_argument("--prompt", required=True, help="Task prompt.")
    p_dispatch.add_argument("--name", help="Display name or local Kimi job label.")
    p_dispatch.add_argument("--model", help="Model or model alias.")
    p_dispatch.add_argument(
        "--effort", choices=["low", "medium", "high", "xhigh", "max"], help="Claude only."
    )
    p_dispatch.add_argument(
        "--permission-mode",
        choices=["acceptEdits", "auto", "bypassPermissions", "default", "dontAsk", "plan"],
        help="Claude only; defaults to auto. Kimi -p always uses auto.",
    )
    p_dispatch.add_argument("--add-dir", action="append", default=[])
    p_dispatch.add_argument("--use-current-anthropic-env", action="store_true", help="Claude only.")
    p_dispatch.add_argument("--settings-keepalive-seconds", type=float, default=20)
    p_dispatch.add_argument("--dangerously-skip-permissions", action="store_true", help="Claude only.")
    p_dispatch.add_argument("--session", help="Kimi only: resume this session ID.")
    p_dispatch.add_argument(
        "--continue", dest="continue_session", action="store_true", help="Kimi only: continue latest session."
    )
    p_dispatch.add_argument(
        "--output-format",
        choices=["text", "stream-json"],
        default="text",
        help="Kimi only.",
    )
    p_dispatch.set_defaults(func=cmd_dispatch)

    for name, func in (("stop", cmd_stop), ("respawn", cmd_respawn), ("rm", cmd_rm)):
        command_parser = sub.add_parser(name, help="%s a Claude or Kimi job." % name.capitalize())
        command_parser.add_argument("id")
        add_backend_argument(command_parser, ["auto", "claude", "kimi"], "auto")
        if name == "stop":
            command_parser.add_argument("--timeout", type=float, default=3.0)
        command_parser.set_defaults(func=func)

    return parser


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "_run-kimi-job":
        try:
            return worker_run_kimi_job(sys.argv[2])
        except Exception as exc:
            print("code_agent_control.py worker: %s" % exc, file=sys.stderr)
            return 1
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "dispatch" and args.backend is None:
        parser.error("dispatch requires --backend claude or --backend kimi")
    try:
        return int(args.func(args))
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, end="", file=sys.stdout)
        if exc.stderr:
            print(exc.stderr, end="", file=sys.stderr)
        return int(exc.returncode)
    except Exception as exc:
        print("code_agent_control.py: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
