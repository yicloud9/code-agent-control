from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "code-agent-control"


def test_skill_package_has_required_files():
    assert (SKILL / "SKILL.md").is_file()
    assert (SKILL / "agents" / "openai.yaml").is_file()
    assert (SKILL / "scripts" / "code_agent_control.py").is_file()
    assert (SKILL / "references" / "hooks.md").is_file()


def test_skill_frontmatter_has_name_and_description():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    assert "name: code-agent-control" in frontmatter
    assert "description:" in frontmatter
