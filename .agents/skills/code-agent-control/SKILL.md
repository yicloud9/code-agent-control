---
name: code-agent-control
description: Dispatch, inspect, and manage coding-agent tasks from Codex through one controller for both Claude Code and Kimi Code. Use when the user asks Codex to start work in Claude Code or Kimi Code, choose between those agents, check whether either agent is busy/done/failed, inspect task logs, determine whether Claude is waiting for permission or input, resume or respawn work, or stop/remove managed coding-agent jobs.
---

# Code Agent Control

## Core Rules

Use the bundled controller as the common control plane. Always choose the backend explicitly when dispatching:

```bash
python3 <skill-dir>/scripts/code_agent_control.py dispatch --backend claude ...
python3 <skill-dir>/scripts/code_agent_control.py dispatch --backend kimi ...
```

Treat the two status sources accurately:

- Claude uses Claude Code's native background-session commands (`--bg`, `agents`, `logs`, `stop`, `respawn`, and `rm`).
- Kimi Code does not expose the same background-job commands. The controller runs official non-interactive `kimi -p` in a detached local worker and records its PID, state, stdout, stderr, and exit code under `~/.codex/code-agent-control/kimi-jobs/`.
- Do not describe the Kimi wrapper state as a native Kimi server or session status. It is managed local-process status.
- Do not inject keystrokes into an ordinary foreground Claude or Kimi TUI. Foreground sessions can be observed, but reliable controller operations require a Claude native background job or a Kimi job dispatched by this wrapper.

## Preflight

Check only the backend needed for the task:

```bash
claude --version
claude agents --json --all

kimi --version
kimi doctor
```

If Kimi is absent, report that it must be installed and authenticated; do not silently install it. Official Kimi Code CLI setup uses `kimi login` for the device-code login flow.

The controller checks `PATH` first, then the standard user install locations `~/.kimi-code/bin/kimi` and `~/.local/bin/claude`. Source the user's shell configuration only when a nonstandard installation still cannot be found.

## Dispatch

Always pass `--cwd`; do not rely on Codex's current directory unless the user explicitly wants it.

### Claude Code

```bash
python3 <skill-dir>/scripts/code_agent_control.py dispatch \
  --backend claude \
  --cwd /path/to/project \
  --name short-task-name \
  --model claude-opus-4-6 \
  --permission-mode auto \
  --use-current-anthropic-env \
  --prompt "Concrete task for Claude Code."
```

Default Claude to `--permission-mode auto`. Do not use `--dangerously-skip-permissions` or `bypassPermissions` unless the user explicitly asks and accepts the risk.

Use `--use-current-anthropic-env` when the current process has gateway variables such as `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, or `ANTHROPIC_API_KEY`. The controller passes them through a temporary settings file and removes it after the worker initializes; do not persist secrets into a project settings file unless requested.

### Kimi Code

```bash
python3 <skill-dir>/scripts/code_agent_control.py dispatch \
  --backend kimi \
  --cwd /path/to/project \
  --name short-task-name \
  --model kimi-code/kimi-for-coding \
  --prompt "Concrete task for Kimi Code."
```

Kimi dispatch uses `kimi --prompt`, whose non-interactive mode uses automatic permission handling and cannot be combined with Kimi's interactive `--auto`, `--yolo`, or `--plan` flags. Do not pass Claude-only permission, effort, or Anthropic-environment options to Kimi.

Pass the model alias registered in `~/.kimi-code/config.toml`, not only the provider model ID. For example, this machine registers `kimi-code/kimi-for-coding` with provider model ID `kimi-for-coding`. The controller reads the local `[models]` table and normalizes a unique provider model ID to its registered alias before starting the worker; an unknown model fails before a background job is created.

Optional Kimi controls:

```bash
# Continue the latest session for this cwd.
python3 <skill-dir>/scripts/code_agent_control.py dispatch --backend kimi \
  --cwd /path/to/project --continue --prompt "Continue and finish the task."

# Resume a specific Kimi session.
python3 <skill-dir>/scripts/code_agent_control.py dispatch --backend kimi \
  --cwd /path/to/project --session <session-id> --prompt "Review the current state."

# Capture Kimi's stream-json output verbatim in the managed stdout log.
python3 <skill-dir>/scripts/code_agent_control.py dispatch --backend kimi \
  --cwd /path/to/project --output-format stream-json --prompt "Run the checks."
```

`--continue` and `--session` are mutually exclusive. Kimi credentials come from its own login/configuration; do not assume exported `KIMI_API_KEY` is read automatically.

## Query and Logs

List one or both backends:

```bash
python3 <skill-dir>/scripts/code_agent_control.py list --backend all --all
python3 <skill-dir>/scripts/code_agent_control.py list --backend claude --cwd /path/to/project --all
python3 <skill-dir>/scripts/code_agent_control.py list --backend kimi --cwd /path/to/project --all
```

Kimi IDs start with `kimi-`, so these commands infer the backend. Claude native IDs are treated as Claude:

```bash
python3 <skill-dir>/scripts/code_agent_control.py status <job-id>
python3 <skill-dir>/scripts/code_agent_control.py logs <job-id>
python3 <skill-dir>/scripts/code_agent_control.py logs <kimi-job-id> --tail 300
```

For Claude, use live fields such as `state`, `status`, and `waitingFor` to answer whether it is waiting for input or permission. For Kimi, report the managed worker's `queued`, `working`, `done`, `failed`, or `stopped` state and its `exitCode`; inspect stdout/stderr before explaining a failure.

Summarize relevant output. Do not dump long logs unless asked.

## Stop, Respawn, and Remove

Confirm with the user immediately before stopping, respawning, or removing a job unless the user explicitly requested that action in the current turn.

```bash
python3 <skill-dir>/scripts/code_agent_control.py stop <job-id>
python3 <skill-dir>/scripts/code_agent_control.py respawn <job-id>
python3 <skill-dir>/scripts/code_agent_control.py rm <job-id>
```

For Kimi, stop terminates the detached process group, respawn creates a new managed job with the saved prompt/options, and remove deletes the local job directory. Stop an active Kimi job before respawning or removing it.

## Hooks

When the user asks for durable telemetry or reusable agent-side integrations, read `references/hooks.md`. Hooks complement the controller's normal status source; they do not replace it.

## Limitations

- Claude foreground sessions and Kimi TUI sessions are not retroactively controllable by this wrapper.
- A Kimi managed job represents one `kimi -p` invocation. Kimi conversation history remains in Kimi's own session store; the wrapper only tracks the detached process and its logs.
- `ps` can show that a process is alive, but it cannot prove what an interactive agent is waiting for.
- UI automation is a fallback only when the user explicitly asks for direct UI control and the applicable Computer Use policy permits it.
