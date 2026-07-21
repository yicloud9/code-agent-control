# Architecture and Release Checklist

## Source boundaries

- `.agents/skills/code-agent-control/SKILL.md` is the runtime procedure and trigger contract.
- `.agents/skills/code-agent-control/agents/openai.yaml` is UI metadata for the Skill catalog.
- `.agents/skills/code-agent-control/scripts/code_agent_control.py` is the stable CLI entrypoint.
- Backend-specific behavior should move behind small adapters as it grows; keep lifecycle state and model-registry parsing separate from argument parsing.
- `tests/` owns deterministic fake-CLI and config fixtures. Do not put test harnesses in the Skill package.
- `tools/install_skill.py` copies the tested Skill package to the user-global installation directory.

Do not edit `~/.codex/skills/code-agent-control` as the source of truth. It is an installation target.

## Backend contract

Every backend exposed by the CLI should implement the same logical operations:

```text
dispatch -> list -> status -> logs -> stop -> respawn -> rm
```

Claude status comes from native Claude background sessions. Kimi status comes from the controller's detached local worker and must remain labeled `managed-local-process`.

Model names are configuration data, not assumptions. Kimi dispatch reads the configured `[models]` aliases and resolves a unique provider model ID before creating a worker. Unknown or ambiguous names must fail before a background job is created.

## Release checklist

1. Run `pytest` and Python compilation checks.
2. Run the Skill frontmatter/shape validation.
3. Run fake Claude/Kimi lifecycle tests.
4. Run one harmless real smoke task for each installed backend.
5. Scan the Git diff for credentials, local absolute paths, state directories, and raw logs.
6. Run `python3 tools/install_skill.py --force` into a temporary target and verify the installed Skill.
7. Tag a semantic version and publish release notes.

Do not put real API credentials or live-provider smoke tests in GitHub Actions.
