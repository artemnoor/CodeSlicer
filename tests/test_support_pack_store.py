import pytest
from pathlib import Path
from impact_engine.support_packs.store import SupportPackStore
from impact_engine.support_packs.schema import SupportPack


def test_support_pack_store_operations(tmp_path):
    store = SupportPackStore(tmp_path)
    
    # 1. List packs on empty store
    assert store.list_packs() == []
    
    # 2. Save a pack
    pack = SupportPack(
        library="fastapi",
        version_range=">=0.80.0",
        language="Python",
        status="verified",
        edge_rules=[]
    )
    
    saved_file = store.save_pack(pack)
    assert saved_file.exists()
    assert "python/fastapi/support_pack.json" in saved_file.as_posix()
    
    # 3. Retrieve pack via get_pack (new layout)
    retrieved = store.get_pack("python", "fastapi")
    assert retrieved is not None
    assert retrieved.library == "fastapi"
    assert retrieved.language == "Python"
    
    # 4. Retrieve pack via backward-compatible lookup (old layout)
    # Manually place it in old layout: root / library / support_pack.json
    old_dir = tmp_path / "gin"
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / "support_pack.json").write_text("""{
        "library": "gin",
        "version_range": ">=1.7.0",
        "language": "Go",
        "status": "experimental",
        "sources": [],
        "patterns": [],
        "edge_rules": [],
        "confidence_rules": [],
        "playground_cases": []
    }""", encoding="utf-8")
    
    retrieved_old = store.get_pack("Go", "gin")
    assert retrieved_old is not None
    assert retrieved_old.library == "gin"
    assert retrieved_old.language == "Go"
    
    # 5. Find by import name
    found = store.find_by_import("fastapi")
    assert found is not None
    assert found.library == "fastapi"


def test_support_pack_store_validate_and_save(tmp_path):
    store = SupportPackStore(tmp_path)
    
    invalid_data = {
        "library": "",
        "version_range": ">=1.0.0"
        # missing fields
    }
    
    res = store.validate_and_save_pack(invalid_data)
    assert res["valid"] is False
    assert len(res["errors"]) > 0
    
    valid_data = {
        "library": "react",
        "version_range": ">=17.0.0",
        "language": "javascript",
        "status": "verified",
        "sources": [],
        "patterns": [],
        "edge_rules": [],
        "confidence_rules": [],
        "playground_cases": []
    }
    
    res_valid = store.validate_and_save_pack(valid_data)
    assert res_valid["valid"] is True
    assert res_valid["path"] is not None
    assert Path(res_valid["path"]).exists()
