import json
from pathlib import Path


ROOT = Path(__file__).parent.parent


def test_acceptance_status_true_requires_recorded_pytest_success():
    status_path = ROOT / "tests" / "fixtures" / "release" / "acceptance_status.json"
    verification_path = ROOT / "tests" / "fixtures" / "release" / "pytest_verification.json"

    status = json.loads(status_path.read_text(encoding="utf-8"))
    if not status.get("tests_passed"):
        assert status.get("blocking_issue")
        return

    assert verification_path.exists(), "tests_passed=true requires docs/pytest_verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    assert verification.get("command") == status.get("full_pytest_command")
    assert verification.get("exit_code") == 0
    assert verification.get("completed") is True
    assert verification.get("tests_passed") is True
    assert verification.get("summary") == status.get("full_pytest_summary")
