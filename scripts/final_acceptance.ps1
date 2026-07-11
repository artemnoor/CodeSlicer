# scripts/final_acceptance.ps1
$env:PYTHONPATH="src"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Running Final Acceptance Script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Clean artifact check
Write-Host "1. Checking repository for temporary files..." -ForegroundColor Green
$temp_files = Get-ChildItem -Path . -Recurse -Include "tmp_*.json", "graph.json", "database.db" -ErrorAction SilentlyContinue
if ($temp_files) {
    Write-Host "Warning: found temporary files that should be cleaned: $temp_files" -ForegroundColor Yellow
} else {
    Write-Host "Clean check passed: No temporary graphs or database files found." -ForegroundColor Gray
}

# 2. Pytest full suite
Write-Host "`n2. Running full pytest suite..." -ForegroundColor Green
python -m pytest -ra
if ($LASTEXITCODE -ne 0) {
    Write-Error "Pytest suite failed."
    exit 1
}

# Define fixture path
$fixture_path = "tests/fixtures/final_acceptance_project"
$out_graph = "tmp_final_acceptance_graph.json"

# 3. CLI analyze
Write-Host "`n3. Running CLI analyze on final acceptance project..." -ForegroundColor Green
python -m impact_engine.cli --json analyze $fixture_path --out $out_graph
if ($LASTEXITCODE -ne 0) {
    Write-Error "CLI analyze failed."
    exit 1
}

# 4. CLI impact
Write-Host "`n4. Running CLI impact query..." -ForegroundColor Green
python -m impact_engine.cli --json impact $out_graph --symbol "HTTP POST /api/orders/" --direction downstream --min-confidence 0.45
if ($LASTEXITCODE -ne 0) {
    Write-Error "CLI impact query failed."
    exit 1
}

# 5. CLI explain-edge
Write-Host "`n5. Running CLI explain-edge query..." -ForegroundColor Green
python -m impact_engine.cli --json explain-edge $out_graph --from "HTTP POST /api/orders/" --to "app.routers.create_order"
if ($LASTEXITCODE -ne 0) {
    Write-Error "CLI explain-edge failed."
    exit 1
}

# 6. MCP tools/list
Write-Host "`n6. Inspecting MCP tool definition list..." -ForegroundColor Green
python -c "from impact_engine.mcp.server import TOOLS; print(f'Loaded {len(TOOLS)} MCP tools.')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "MCP list tools check failed."
    exit 1
}

# 7. MCP analyze_project
Write-Host "`n7. Running MCP analyze_project..." -ForegroundColor Green
python -c "from impact_engine.mcp.server import analyze_project; res = analyze_project('$fixture_path'); assert res['status'] == 'ok'; print('MCP analyze_project OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "MCP analyze_project check failed."
    exit 1
}

# 8. Support pack validate
Write-Host "`n8. Validating support packs..." -ForegroundColor Green
python -c "from impact_engine.mcp.server import validate_support_pack; res = validate_support_pack('support_packs/python/fastapi/support_pack.json'); assert res['status'] == 'ok'; print('FastAPI support pack validation OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Support pack validation check failed."
    exit 1
}

# 9. Research workflow start/build-input
Write-Host "`n9. Testing Research Workflow creation and build-input..." -ForegroundColor Green
python -c "from impact_engine.mcp.server import create_library_research_workflow, prepare_library_research_input; wf = create_library_research_workflow('$fixture_path', 'unknown_custom_lib', 'python'); assert wf['status'] == 'ok'; res = prepare_library_research_input(wf['workflow_id'], allow_network=False); assert res['status'] == 'ok'; print('Research workflow dry run OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Research workflow check failed."
    exit 1
}

# Cleanup
if (Test-Path $out_graph) {
    Remove-Item $out_graph
}

Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "All Acceptance Checks Passed Successfully!" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
