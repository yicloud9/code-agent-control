# Contributing

## Development setup

```bash
python3 -m pip install -e '.[dev]'
pytest
```

Keep the installable Skill under `.agents/skills/code-agent-control/`. Do not edit the user-global copy as the source of truth.

## Pull requests

- Keep changes focused and explain the backend impact.
- Add or update deterministic tests for controller behavior.
- Never add credentials, local job state, raw provider logs, or user-specific absolute paths.
- Do not add live-provider calls to CI.
- Run the release checklist in `docs/architecture.md` before requesting review.
