from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from impact_engine import cli
from impact_engine.agent_integration import bundled_skills, client_catalog, install, installation_status, plan_install, repair, uninstall
from impact_engine.terminal_ui import choose_agent_clients


def test_bundled_install_assets_are_valid_and_limited_to_two_skills() -> None:
    assets = bundled_skills()
    assert set(assets) == {"codeslicer-impact-analysis", "graphify-architecture-analysis"}
    assert all(value["metadata"]["name"] == name and value["source_hash"] for name, value in assets.items())


def test_kodik_catalog_uses_documented_native_skill_and_jsonc_contract() -> None:
    kodik = next(item for item in client_catalog() if item["id"] == "kodik")
    assert kodik["status"] == "verified"
    assert kodik["integration"] == "native-skill"
    assert kodik["project_skills"] and kodik["user_skills"] and kodik["user_mcp"]


def test_kodik_install_preserves_jsonc_comment_and_other_server(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    home = tmp_path / "home"
    config = home / "AppData" / "Roaming" / "User" / "globalStorage" / "kodik.chat" / "settings" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text('{\n  // managed by Kodik\n  "servers": {"other": {"command": "node"}}\n}\n', encoding="utf-8")

    result = install(["kodik"], project_path=project, home=home)

    assert result["status"] == "ok"
    assert (project / ".kodik" / "skills" / "codeslicer-impact-analysis" / "SKILL.md").is_file()
    assert (project / ".kodik" / "skills" / "graphify-architecture-analysis" / "SKILL.md").is_file()
    rendered = config.read_text(encoding="utf-8")
    assert "// managed by Kodik" in rendered and '"other"' in rendered and '"codeslicer"' in rendered
    assert "autoApprove" not in rendered
    assert json.loads((project / ".codeslicer" / "agent-install.json").read_text(encoding="utf-8"))["clients"]["kodik"]["mcp"]["server_name"] == "codeslicer"


def test_kodik_dry_run_does_not_create_project_files(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    result = install(["kodik"], project_path=project, home=tmp_path / "home", skills_only=True, dry_run=True)
    assert result["changed"] is False
    assert not (project / ".kodik").exists() and not (project / ".codeslicer").exists()
    assert len(plan_install(["kodik"], project_path=project, skills_only=True)["writes"]) == 2


def test_kodik_reinstall_is_idempotent_and_uninstall_removes_only_owned_entry(tmp_path: Path) -> None:
    project = tmp_path / "проект с пробелом"; project.mkdir()
    home = tmp_path / "home"
    config = home / "AppData" / "Roaming" / "User" / "globalStorage" / "kodik.chat" / "settings" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text('{\n  "servers": {\n    "other": {"command": "node"}\n  }\n}\n', encoding="utf-8")

    first = install(["kodik"], project_path=project, home=home)
    second = install(["kodik"], project_path=project, home=home)
    assert first["status"] == "ok" and second["status"] == "already_installed"
    assert installation_status(project_path=project, home=home)["result"]["clients"]["kodik"]["mcp"]["registered"] is True

    removed = uninstall(project_path=project, home=home)
    assert removed["status"] == "ok"
    after = config.read_text(encoding="utf-8")
    assert '"other"' in after and '"codeslicer"' not in after
    assert not (project / ".kodik" / "skills" / "codeslicer-impact-analysis" / "SKILL.md").exists()
    assert not (project / ".codeslicer" / "agent-install.json").exists()


def test_uninstall_preserves_user_modified_skill_and_mcp_entry(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    home = tmp_path / "home"
    config = home / "AppData" / "Roaming" / "User" / "globalStorage" / "kodik.chat" / "settings" / "mcp.json"
    config.parent.mkdir(parents=True); config.write_text('{"servers": {}}', encoding="utf-8")
    install(["kodik"], project_path=project, home=home)
    skill = project / ".kodik" / "skills" / "codeslicer-impact-analysis" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nUser note.\n", encoding="utf-8")
    result = uninstall(project_path=project, home=home)
    assert result["status"] == "partial"
    assert skill.exists() and '"codeslicer"' not in config.read_text(encoding="utf-8")
    assert (project / ".codeslicer" / "agent-install.json").is_file()


def test_codex_user_scope_uses_a_scoped_toml_mcp_section(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('# keep this comment\nmodel = "test"\n', encoding="utf-8")
    result = install(["codex"], scope="user", project_path=project, home=home)
    assert result["status"] == "ok"
    rendered = config.read_text(encoding="utf-8")
    assert '# keep this comment' in rendered and '[mcp_servers.codeslicer]' in rendered
    status = installation_status(scope="user", project_path=project, home=home)
    assert status["result"]["clients"]["codex"]["mcp"]["registered"] is True


def test_compatibility_document_lists_every_registry_adapter() -> None:
    document = (Path(__file__).parents[1] / "docs" / "AGENT_CLIENT_COMPATIBILITY.md").read_text(encoding="utf-8")
    for adapter in client_catalog():
        assert adapter["display_name"] in document


def test_repair_reconstructs_lost_state_from_exact_managed_files(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    install(["codex"], project_path=project, skills_only=True)
    state = project / ".codeslicer" / "agent-install.json"
    state.unlink()
    result = repair(project_path=project)
    assert result["status"] == "already_installed"
    assert state.is_file()
    assert any("reconstructed" in warning for warning in result["warnings"])


def test_interactive_install_offers_supported_ide_choices_when_nothing_is_detected(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("impact_engine.agent_integration.detect_clients", lambda _project: [])
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("impact_engine.terminal_ui.choose_agent_clients", lambda catalog, detected: ["codex"])

    cli.main(["agent", "install", "--project", str(tmp_path), "--dry-run"])

    output = capsys.readouterr().out
    assert '"client": "codex"' in output
    assert '"scope": "user"' in output


def test_terminal_menu_uses_checkbox_selection_with_keyboard_instructions(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeQuestion:
        def ask(self):
            return ["kodik"]

    def checkbox(message, **kwargs):
        seen["message"] = message
        seen.update(kwargs)
        return FakeQuestion()

    fake_questionary = SimpleNamespace(
        Choice=lambda title, *, value, checked: {"title": title, "value": value, "checked": checked},
        checkbox=checkbox,
    )
    monkeypatch.setitem(sys.modules, "questionary", fake_questionary)

    selected = choose_agent_clients(
        {"codex": {"display_name": "Codex", "status": "verified"}, "kodik": {"display_name": "Kodik", "status": "verified"}},
        [{"id": "kodik", "confidence": "configured"}],
    )

    assert selected == ["kodik"]
    assert seen["message"] == "Choose IDEs to configure"
    assert "Space select" in str(seen["instruction"])
    assert seen["choices"][1]["checked"] is True
