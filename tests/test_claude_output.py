import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / ".agents" / "skills" / "code-agent-control" / "scripts" / "code_agent_control.py"


def load_controller():
    spec = importlib.util.spec_from_file_location("code_agent_control", CONTROLLER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extract_claude_job_id_handles_colored_output():
    controller = load_controller()
    output = "\x1b[36mbackgrounded · e381a922 · task\x1b[39m"

    assert controller.extract_claude_job_id(output) == "e381a922"


def test_extract_claude_job_id_accepts_mixed_stream_output():
    controller = load_controller()

    assert controller.extract_claude_job_id("warning\ne381a922\n") == "e381a922"
    assert controller.extract_claude_job_id("no job id") is None


def test_discover_claude_job_id_uses_newest_matching_background_job():
    controller = load_controller()
    controller.claude_list = lambda cwd, include_all: [
        {
            "id": "deadbeef",
            "cwd": cwd,
            "kind": "background",
            "name": "new-task",
            "startedAt": 10010,
        },
        {
            "id": "oldjob00",
            "cwd": cwd,
            "kind": "background",
            "name": "new-task",
            "startedAt": 10000,
        },
    ]

    assert controller.discover_claude_job_id("/tmp/project", "new-task", 10000) == "deadbeef"
