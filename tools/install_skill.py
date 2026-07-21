#!/usr/bin/env python3
"""Install the repository's tested Skill package into a Codex skill directory."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


SKILL_NAME = "code-agent-control"
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / ".agents" / "skills" / SKILL_NAME


def default_target() -> Path:
    configured = os.environ.get("CODEX_HOME")
    root = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return root / "skills" / SKILL_NAME


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=default_target())
    parser.add_argument("--force", action="store_true", help="Replace an existing installation.")
    args = parser.parse_args()

    if not (SOURCE / "SKILL.md").is_file():
        parser.error("repository Skill package is missing: %s" % SOURCE)
    if args.target.exists() and not args.force:
        parser.error("target exists; pass --force to replace it: %s" % args.target)

    args.target.parent.mkdir(parents=True, exist_ok=True)
    if args.target.exists():
        shutil.rmtree(args.target)
    shutil.copytree(SOURCE, args.target)
    print("Installed %s to %s" % (SKILL_NAME, args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
