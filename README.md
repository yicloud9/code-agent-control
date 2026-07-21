# Code Agent Control

One Codex Skill for dispatching and monitoring both Claude Code and Kimi Code.

The repository keeps the installable Skill under `.agents/skills/code-agent-control/`. Codex discovers that path when the repository is opened locally. The installed user-global copy is a generated deployment artifact; edit the repository source and run the installer to update it.

## What it supports

- Claude Code native background sessions: dispatch, list, status, logs, stop, respawn, and remove.
- Kimi Code managed workers around `kimi --prompt`: dispatch, list, status, logs, stop, respawn, and remove.
- Kimi model alias resolution from `KIMI_CODE_HOME/config.toml`, including mapping `kimi-for-coding` to a registered alias such as `kimi-code/kimi-for-coding`.
- Local-only job state and logs; no credentials are stored by the controller.

## Install

Clone this repository, then run:

```bash
python3 tools/install_skill.py --force
```

This installs the Skill to `${CODEX_HOME:-~/.codex}/skills/code-agent-control`. Start a new Codex task after installation so the Skill catalog refreshes.

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
