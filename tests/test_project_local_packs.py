import json

from impact_engine.analysis.pipeline import analyze_project_core
from impact_engine.project_packs import install_project_pack, list_project_packs, project_pack_root
from tests.helpers.cli_runner import run_cli


def _write_project(project):
    project.mkdir()
    (project / "orders.py").write_text(
        "import acme_gateway\n\n"
        "def submit(payload):\n"
        "    return acme_gateway.submit_order(payload)\n",
        encoding="utf-8",
    )


def _write_candidate(path, *, name_only=False):
    match = {"method": "submit_order"} if name_only else {
        "method": "submit_order",
        "receiver": "acme_gateway",
        "imported_library": "acme_gateway",
    }
    path.write_text(json.dumps({
        "library": "acme_gateway",
        "version_range": ">=1.0",
        "language": "python",
        "status": "draft",
        "sources": [{"type": "project_source", "url": "local://acme_gateway-wrapper"}],
        "patterns": [],
        "edge_rules": [{
            "id": "acme-submit-order",
            "type": "method_call_alias",
            "match": match,
            "emit": {
                "kind": "DEPENDS_ON",
                "to": "module:acme_gateway",
                "source": "SUPPORT_PACK",
                "confidence": 0.80,
                "description": "Project gateway wrapper resolves to its imported module",
            },
        }],
        "confidence_rules": [],
        "playground_cases": [],
        "evidence_requirements": {"forbid_name_only": True, "required": ["import", "receiver"]},
    }, indent=2), encoding="utf-8")


def _project_edges(result):
    return [
        edge for edge in result["graph"]["edges"]
        if edge["properties"].get("support_pack_rule_id") == "acme-submit-order"
    ]


def test_project_local_pack_is_scoped_and_applies_only_to_its_project(tmp_path):
    project = tmp_path / "project"
    other_project = tmp_path / "other-project"
    _write_project(project)
    _write_project(other_project)
    candidate = tmp_path / "acme-pack.json"
    _write_candidate(candidate)

    installed = install_project_pack(project, candidate, trust_level="experimental")

    assert installed["status"] == "installed"
    assert installed["scope"] == "project_local"
    assert installed["active"] is True
    assert project_pack_root(project).joinpath("python", "acme_gateway", "support_pack.json").is_file()
    assert not project_pack_root(other_project).exists()

    result = analyze_project_core(str(project), support_pack_root=str(tmp_path / "global-packs"), create_research_requests=False)
    edges = _project_edges(result)
    assert len(edges) == 1
    edge = edges[0]
    assert edge["from"] == "orders.submit"
    assert edge["to"] == "module:acme_gateway"
    assert edge["confidence"] == 0.65
    assert edge["properties"]["support_pack"]["scope"] == "project_local"
    assert edge["properties"]["support_pack"]["project_scope"]["project_name"] == "project"
    assert edge["properties"].get("status") != "suspicious"

    other_result = analyze_project_core(str(other_project), support_pack_root=str(tmp_path / "global-packs"), create_research_requests=False)
    assert _project_edges(other_result) == []


def test_name_only_project_pack_is_rejected(tmp_path):
    project = tmp_path / "project"
    _write_project(project)
    candidate = tmp_path / "weak-pack.json"
    _write_candidate(candidate, name_only=True)

    result = install_project_pack(project, candidate, trust_level="experimental")

    assert result["status"] == "error"
    assert any("name-only matching is forbidden" in error for error in result["errors"])
    assert not project_pack_root(project).exists()


def test_draft_project_pack_is_visible_but_does_not_change_graph(tmp_path):
    project = tmp_path / "project"
    _write_project(project)
    candidate = tmp_path / "draft-pack.json"
    _write_candidate(candidate)

    installed = install_project_pack(project, candidate)
    result = analyze_project_core(str(project), support_pack_root=str(tmp_path / "global-packs"), create_research_requests=False)

    assert installed["status"] == "installed"
    assert installed["active"] is False
    assert _project_edges(result) == []
    listed = list_project_packs(project)
    assert listed[0]["scope"] == "project_local"
    assert listed[0]["active"] is False


def test_project_local_pack_cannot_be_promoted_to_global_trusted(tmp_path):
    project = tmp_path / "project"
    _write_project(project)
    candidate = tmp_path / "trusted-pack.json"
    _write_candidate(candidate)

    result = install_project_pack(project, candidate, trust_level="trusted")

    assert result["status"] == "error"
    assert not project_pack_root(project).exists()


def test_cli_initializes_installs_and_lists_project_local_packs(tmp_path):
    project = tmp_path / "project"
    _write_project(project)
    candidate = tmp_path / "candidate.json"
    _write_candidate(candidate)

    initialized = run_cli(["--json", "project-packs", "init", str(project)], cwd=tmp_path)
    installed = run_cli([
        "--json", "project-packs", "install", str(project), str(candidate),
        "--trust-level", "experimental",
    ], cwd=tmp_path)
    listed = run_cli(["--json", "project-packs", "list", str(project)], cwd=tmp_path)

    assert json.loads(initialized.stdout)["scope"] == "project_local"
    assert json.loads(installed.stdout)["status"] == "installed"
    packs = json.loads(listed.stdout)["packs"]
    assert len(packs) == 1
    assert packs[0]["active"] is True
