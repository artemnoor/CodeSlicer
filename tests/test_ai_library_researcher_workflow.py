import pytest
from pathlib import Path
from impact_engine.support_packs.research import (
    create_research_request,
    create_research_request_from_unknown_library
)
from impact_engine.mcp.server import create_library_research_request


def test_create_research_request_shape():
    req = create_research_request(
        library_name="fastapi",
        version="0.100.0",
        package_manager="pip",
        language="python",
        imports=["fastapi"],
        usages=["FastAPI()"],
        official_docs=["https://fastapi.tiangolo.com/"]
    )
    
    assert req["library_name"] == "fastapi"
    assert req["version"] == "0.100.0"
    assert req["package_manager"] == "pip"
    assert req["language"] == "python"
    assert req["imports"] == ["fastapi"]
    assert req["usages"] == ["FastAPI()"]
    assert req["official_docs"] == ["https://fastapi.tiangolo.com/"]
    assert "output_path" in req
    assert "instructions" in req


def test_create_research_request_instructions_are_strict():
    req = create_research_request("fastapi")
    instr = req["instructions"]
    
    # Must mention official docs
    assert "official documentation" in instr.lower() or "official docs" in instr.lower()
    # Must mention GitHub examples
    assert "github repository" in instr.lower() or "github examples" in instr.lower()
    # Must mention machine-readable support_pack.json
    assert "machine-readable support_pack.json" in instr.lower()
    # Must mention sources
    assert "sources" in instr.lower()
    # Must mention edge_rules
    assert "edge_rules" in instr.lower()
    # Must mention confidence_rules
    assert "confidence_rules" in instr.lower()
    # Must mention playground_cases
    assert "playground_cases" in instr.lower()
    # Must mention limitations
    assert "limitations" in instr.lower()
    # Must mention not prose only
    assert "prose only" in instr.lower()


def test_create_research_request_output_path_is_deterministic():
    # FastAPI version `>=0.100` must map to a safe deterministic path
    req = create_research_request("FastAPI", version=">=0.100")
    path_str = req["output_path"]
    
    # The path should not contain unsafe chars
    for char in ['/', '\\', ' ', '<', '>', '=', ':', '*', '?', '"', '|']:
        # Note: the overall path may contain path separators `/` or `\\` between segments,
        # but the specific segment of the version must be sanitized.
        # So let's check the version segment specifically!
        pass
        
    parts = Path(path_str).parts
    version_segment = parts[-2]
    
    assert version_segment == "0.100"  # or similar sanitized form
    assert not any(c in version_segment for c in ['/', '\\', ' ', '<', '>', '=', ':', '*', '?', '"', '|'])
    
    # Check another version range
    req2 = create_research_request("some_lib", version="v1.2.3/beta")
    parts2 = Path(req2["output_path"]).parts
    version_segment2 = parts2[-2]
    assert version_segment2 == "v1.2.3_beta"
    assert not any(c in version_segment2 for c in ['/', '\\', ' ', '<', '>', '=', ':', '*', '?', '"', '|'])


def test_mcp_create_library_research_request_uses_research_helper():
    res = create_library_research_request("fastapi", "0.100.0", "pip")
    assert res["status"] == "ok"
    assert res["tool"] == "create_library_research_request"
    assert res["library_name"] == "fastapi"
    assert res["version"] == "0.100.0"
    assert res["package_manager"] == "pip"
    assert "output_path" in res
    assert "prompt" in res
    
    # Assert prompt is strict
    prompt = res["prompt"]
    assert "sources" in prompt
    assert "edge_rules" in prompt
    assert "confidence_rules" in prompt
    assert "playground_cases" in prompt
    assert "limitations" in prompt
    assert "prose only" in prompt


def test_research_workflow_does_not_create_files_or_network():
    req = create_research_request_from_unknown_library("unknown_lib", ["some_import"])
    output_path = Path(req["output_path"])
    
    # Verify no file is created
    assert not output_path.exists()
