# Code Agent Control

One Codex Skill for dispatching and monitoring both Claude Code and Kimi Code.

The repository keeps the Codex Skill under `.agents/skills/code-agent-control/`. When Codex opens this repository, it discovers the project-local Skill automatically. The user-global copy is only for using the Skill from unrelated projects.

## What it supports

- Claude Code native background sessions: dispatch, list, status, logs, stop, respawn, and remove.
- Kimi Code managed workers around `kimi --prompt`: dispatch, list, status, logs, stop, respawn, and remove.
- Kimi model alias resolution from `KIMI_CODE_HOME/config.toml`, including mapping `kimi-for-coding` to a registered alias such as `kimi-code/kimi-for-coding`.
- Local-only job state and logs; no credentials are stored by the controller.

## Use from this repository (recommended)

After opening the repository in Codex, invoke the Skill by name and choose the backend in your request:

```text
Use $code-agent-control and dispatch this task to Claude Code.
Use $code-agent-control and dispatch this task to Kimi Code.
```

Codex is the controller; Claude Code and Kimi Code are the execution backends. You do not need to install the Skill for every task.

## Optional global installation

Install it once only when you want to use `$code-agent-control` from projects that do not contain this repository:

```bash
python3 tools/install_skill.py
```

If the global copy already exists and you are updating it, replace it explicitly:

```bash
python3 tools/install_skill.py --force
```

This installs the Skill to `${CODEX_HOME:-~/.codex}/skills/code-agent-control`. Start a new Codex task after a global installation so the Skill catalog refreshes.

## Usage

```bash
python3 .agents/skills/code-agent-control/scripts/code_agent_control.py dispatch \
  --backend kimi \
  --cwd /path/to/project \
  --model kimi-code/kimi-for-coding \
  --prompt "Inspect the project and report blockers."

python3 .agents/skills/code-agent-control/scripts/code_agent_control.py dispatch \
  --backend claude \
  --cwd /path/to/project \
  --permission-mode auto \
  --use-current-anthropic-env \
  --prompt "Inspect the project and report blockers."
```

Use `list`, `status`, `logs`, `stop`, `respawn`, and `rm` with the returned job ID. Kimi IDs begin with `kimi-`; the controller uses that prefix to infer the backend for lifecycle commands.

## Development

```bash
python3 -m pip install -e '.[dev]'
pytest
python3 -m py_compile .agents/skills/code-agent-control/scripts/code_agent_control.py
```

The test suite uses fake CLIs and temporary config files. Real Claude/Kimi credentials are never required in CI. Run a real smoke test manually before a release when changing a backend adapter.

See [docs/architecture.md](docs/architecture.md) for the maintenance boundaries and release checklist. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Security

The controller launches local CLIs and stores task output locally. Never commit `.claude/`, `.kimi-code/`, controller job directories, API keys, OAuth tokens, or raw production logs. Report vulnerabilities privately using [SECURITY.md](SECURITY.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
