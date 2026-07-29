from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from impact_engine import cli
from impact_engine.agent_integration import bundled_skills, client_catalog, install, installation_status, plan_install, repair, uninstall
from impact_engine.terminal_ui import InstallationProgress, choose_agent_clients, render_agent_installation_result


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


def test_jsonc_install_adds_missing_mcp_servers_object_without_overwriting_preferences(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    home = tmp_path / "home"
    config = home / ".gemini" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text('{\n  // preserve user preference\n  "theme": "dark"\n}\n', encoding="utf-8")

    result = install(["gemini"], scope="user", project_path=project, home=home)

    assert result["status"] == "ok"
    rendered = config.read_text(encoding="utf-8")
    assert "// preserve user preference" in rendered and '"theme": "dark"' in rendered
    assert json.loads("\n".join(line.split("//", 1)[0] for line in rendered.splitlines()))["mcpServers"]["codeslicer"]["args"] == []


def test_kodik_dry_run_does_not_create_project_files(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    result = install(["kodik"], project_path=project, home=tmp_path / "home", skills_only=True, dry_run=True)
    assert result["changed"] is False
    assert not (project / ".kodik").exists() and not (project / ".codeslicer").exists()
    assert len(plan_install(["kodik"], project_path=project, skills_only=True)["writes"]) == 2


def test_agent_install_reports_real_completed_actions(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    events: list[dict[str, object]] = []

    result = install(["codex"], project_path=project, skills_only=True, progress_callback=events.append)

    assert result["status"] == "ok"
    assert events[0]["phase"] == "preparing"
    assert [event["phase"] for event in events].count("skills") == 2
    assert events[-1] == {"phase": "complete", "completed": 3, "total": 3, "message": "Local setup is ready"}


def test_installation_progress_uses_real_remaining_actions_and_phase_style(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    panel = InstallationProgress(stream=StringIO(), enabled=False)
    panel.update({"phase": "skills", "completed": 2, "total": 5, "message": "Codex: impact analysis"})
    skill_lines = panel._lines(final=False)
    assert "Installing AI skills" in skill_lines[1]
    assert "3 actions left" in skill_lines[2]

    panel.update({"phase": "mcp", "completed": 4, "total": 5, "message": "Codex: MCP registration"})
    assert "Configuring MCP connection" in panel._lines(final=False)[1]


def test_agent_setup_success_card_and_human_summary_are_concise(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    panel = InstallationProgress(stream=StringIO(), enabled=False)
    panel.set_result({"result": {"plan": {"writes": [{"client": "codex", "kind": "skill"}, {"client": "codex", "kind": "mcp"}]}}, "warnings": []})
    panel.update({"phase": "complete", "completed": 2, "total": 2, "message": "Local setup is ready"})

    assert "setup complete" in panel._lines(final=True)[0]
    assert "CodeSlicer IDE setup\n" in render_agent_installation_result({"status": "ok", "result": {"plan": {"writes": [{"client": "codex"}]}}, "warnings": [], "errors": []})


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


def test_cursor_user_scope_falls_back_to_workspace_rules_without_aborting_install(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    home = tmp_path / "home"

    plan = plan_install(["cursor"], scope="user", project_path=project, home=home, skills_only=True)
    result = install(["cursor"], scope="user", project_path=project, home=home, skills_only=True)

    assert result["status"] == "ok"
    assert all(str(project / ".cursor" / "rules") in write["path"] for write in plan["writes"])
    assert (project / ".cursor" / "rules" / "codeslicer-impact-analysis.mdc").is_file()
    assert any("project-level rules" in warning for warning in result["warnings"])


def test_installer_skips_missing_skill_destination_but_keeps_supported_mcp_setup(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    home = tmp_path / "home"

    result = install(["zed"], scope="user", project_path=project, home=home)

    assert result["status"] == "ok"
    assert (home / ".config" / "zed" / "settings.json").is_file()
    assert any("skipped CodeSlicer skills" in warning for warning in result["warnings"])


def test_windows_bootstrap_hides_raw_pip_output_behind_real_stage_progress() -> None:
    script = (Path(__file__).parents[1] / "scripts" / "install-windows.ps1").read_text(encoding="utf-8")

    assert "Invoke-CodeSlicerPipStage" in script
    assert "GetTempFileName" in script and "echo %ERRORLEVEL%" in script
    assert "Installing CodeSlicer and dependencies" in script
    assert "slicing local code into an impact graph" in script
    assert "<====|" in script and "SLICER READY" in script
    assert "& $venvPython -m pip" not in script


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


def test_json_agent_install_keeps_progress_ui_off_stderr(tmp_path: Path, capsys) -> None:
    cli.main(["agent", "install", "--client", "codex", "--project", str(tmp_path), "--skills-only", "--json"])

    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "ok"
    assert captured.err == ""


def test_human_agent_install_prints_a_concise_handoff_not_the_full_plan(tmp_path: Path, capsys) -> None:
    cli.main(["agent", "install", "--client", "codex", "--scope", "project", "--project", str(tmp_path), "--skills-only"])

    output = capsys.readouterr().out
    assert "CodeSlicer IDE setup" in output
    assert "Status: completed" in output
    assert '"command": "agent.install"' not in output


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
