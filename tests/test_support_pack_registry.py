import pytest
import json
from pathlib import Path
from impact_engine.support_packs.schema import (
    validate_support_pack_dict,
    support_pack_from_dict,
    support_pack_to_dict,
    SupportPack
)
from impact_engine.support_packs.registry import (
    load_support_pack,
    validate_support_pack_file,
    find_support_pack,
    import_support_pack_file,
    list_local_support_packs,
)
from impact_engine.mcp.server import validate_support_pack, import_support_pack

EXAMPLE_PACK_PATH = Path(__file__).parent.parent / "support_packs" / "example_library" / "support_pack.json"


def test_validate_example_support_pack_valid():
    content = EXAMPLE_PACK_PATH.read_text(encoding="utf-8")
    data = json.loads(content)
    errors = validate_support_pack_dict(data)
    assert len(errors) == 0, f"Example support pack is invalid: {errors}"


def test_validate_support_pack_rejects_missing_required_fields():
    errors = validate_support_pack_dict({})
    # Assert missing fields list
    assert any("library" in err for err in errors)
    assert any("version_range" in err for err in errors)
    assert any("language" in err for err in errors)
    assert any("status" in err for err in errors)


def test_validate_support_pack_rejects_bad_status():
    data = {
        "library": "lib",
        "version_range": ">=1.0",
        "language": "python",
        "status": "bad_status_value",
        "sources": [],
        "patterns": [],
        "edge_rules": [],
        "confidence_rules": [],
        "playground_cases": []
    }
    errors = validate_support_pack_dict(data)
    assert any("status must be one of" in err for err in errors)


def test_validate_support_pack_rejects_bad_sources():
    data = {
        "library": "lib",
        "version_range": ">=1.0",
        "language": "python",
        "status": "experimental",
        "sources": [{"type": "official_docs"}],  # missing url
        "patterns": [],
        "edge_rules": [],
        "confidence_rules": [],
        "playground_cases": []
    }
    errors = validate_support_pack_dict(data)
    assert any("missing 'url'" in err or "missing url" in err for err in errors)

    data["sources"] = [{"url": "http://example.com"}]  # missing type
    errors = validate_support_pack_dict(data)
    assert any("missing 'type'" in err or "missing type" in err for err in errors)


def test_load_support_pack_returns_structured_pack():
    pack = load_support_pack(EXAMPLE_PACK_PATH)
    assert isinstance(pack, SupportPack)
    assert pack.library == "example_library"
    assert pack.language == "python"
    assert len(pack.sources) == 1
    assert pack.sources[0]["type"] == "official_docs"


def test_find_support_pack_by_library():
    # Registry root is parent of support_packs folder
    support_packs_root = Path(__file__).parent.parent / "support_packs"
    path = find_support_pack("example_library", root=support_packs_root)
    assert path is not None
    assert path.resolve() == EXAMPLE_PACK_PATH.resolve()

    # Searching for non-existent library
    assert find_support_pack("non_existent_library", root=support_packs_root) is None


def test_list_local_support_packs_ignores_staging_directory(tmp_path):
    active = tmp_path / "python" / "fastapi"
    staged = tmp_path / ".staging" / "python" / "fastapi" / "workflow-1"
    active.mkdir(parents=True)
    staged.mkdir(parents=True)
    (active / "support_pack.json").write_text(EXAMPLE_PACK_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (staged / "support_pack.json").write_text('{"library": "bad-staged-draft"}', encoding="utf-8")

    paths = list_local_support_packs(tmp_path)

    assert paths == [active / "support_pack.json"]


def test_import_support_pack_file_to_temp_registry(tmp_path):
    # Import example pack into temporary directory
    res = import_support_pack_file(EXAMPLE_PACK_PATH, registry_root=tmp_path)
    assert res["status"] == "imported"
    
    target_file = tmp_path / "example_library" / "support_pack.json"
    assert target_file.exists()
    
    # Re-reading it from target
    imported_pack = load_support_pack(target_file)
    assert imported_pack.library == "example_library"

    # Attempting to import again should return already_exists
    res_second = import_support_pack_file(EXAMPLE_PACK_PATH, registry_root=tmp_path)
    assert res_second["status"] == "already_exists"


def test_mcp_validate_and_import_support_pack_use_registry(tmp_path):
    # Test validate_support_pack MCP wrapper
    val_res = validate_support_pack(str(EXAMPLE_PACK_PATH))
    assert val_res["tool"] == "validate_support_pack"
    assert val_res["status"] == "ok"
    assert val_res["valid"] is True

    # Test import_support_pack MCP wrapper
    imp_res = import_support_pack(str(EXAMPLE_PACK_PATH), registry_root=str(tmp_path))
    assert imp_res["tool"] == "import_support_pack"
    assert imp_res["status"] == "imported"
    
    target_file = tmp_path / "example_library" / "support_pack.json"
    assert target_file.exists()


def test_import_support_pack_same_path_returns_already_exists():
    res = import_support_pack_file(EXAMPLE_PACK_PATH, registry_root=EXAMPLE_PACK_PATH.parents[1])
    assert res["status"] == "already_exists"
