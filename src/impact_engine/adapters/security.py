"""Local CycloneDX, SPDX, and SARIF security evidence overlays.

The adapters consume already exported JSON reports only.  They do not resolve
packages, contact advisory services, run scanners, or mutate the canonical
Impact Engine graph.  Findings are observational and incomplete reports never
prove that a project is secure.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from impact_engine.models import GraphDocument

SECURITY_OVERLAY_SCHEMA = "CodeSlicerSecurityEvidenceOverlay/v1"
MAX_SECURITY_REPORT_BYTES = 16 * 1024 * 1024
MAX_SECURITY_ITEMS = 50_000
MAX_SECURITY_TEXT_BYTES = 512

_SENSITIVE = re.compile(r"(?:password|passwd|secret|token|authorization|cookie|set-cookie|credential|private[-_.]?key|api[-_.]?key|access[-_.]?key)", re.I)
_SAFE_METADATA_KEYS = {
    "codeslicer.manifest", "codeslicer.lockfile", "manifest", "lockfile",
    "package.manager", "ecosystem", "component.type", "scope",
}
_GENERATED_PATH = re.compile(r"(^|/)(?:node_modules|vendor|obj|bin|dist|build|generated|coverage)(?:/|$)|(?:\.generated\.|\.min\.)", re.I)


def _diag(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _safe_text(value: Any, *, limit: int = MAX_SECURITY_TEXT_BYTES) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    if not text or _SENSITIVE.search(text):
        return None
    if len(text.encode("utf-8")) > limit:
        return None
    return text


def _safe_uri(value: Any, diagnostics: list[dict[str, str]], pointer: str) -> str | None:
    text = _safe_text(value, limit=2048)
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme and parsed.scheme.lower() not in {"file"}:
        diagnostics.append(_diag("external_location_redacted", f"External SARIF location at {pointer} was not retained."))
        return None
    if parsed.username or parsed.password:
        diagnostics.append(_diag("credentialed_url_redacted", f"Credentialed location at {pointer} was not retained."))
        return None
    if parsed.scheme.lower() == "file":
        return unquote(parsed.path)
    return text.replace("\\", "/")


def _read_report(path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    diagnostics: list[dict[str, str]] = []
    if path.stat().st_size > MAX_SECURITY_REPORT_BYTES:
        return {}, [_diag("oversized_report", f"Security report exceeds {MAX_SECURITY_REPORT_BYTES} bytes.", "error")]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        return {}, [_diag("invalid_encoding", "Security report must be UTF-8 JSON.", "error")]
    except json.JSONDecodeError as exc:
        return {}, [_diag("malformed_json", f"Security report JSON is malformed: {exc.msg}.", "error")]
    if not isinstance(value, dict):
        return {}, [_diag("unsupported_format", "Security report root must be a JSON object.", "error")]
    return value, diagnostics


def _id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"security:{prefix}:{digest}"


def _purl(value: Any) -> tuple[str, str, str]:
    text = str(value or "")
    if not text.startswith("pkg:"):
        return "", "", ""
    body = text[4:].split("?", 1)[0].split("#", 1)[0]
    if "/" not in body:
        return "", "", ""
    ecosystem, package = body.split("/", 1)
    package = unquote(package)
    version = ""
    if "@" in package:
        package, version = package.rsplit("@", 1)
    return ecosystem.lower(), package, version


def _properties_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, list):
        return {}
    result: dict[str, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("key") or "").strip().lower()
        value = _safe_text(item.get("value"))
        if name in _SAFE_METADATA_KEYS and value:
            result[name] = value.replace("\\", "/")
    return result


def _component(raw: dict[str, Any], pointer: str, diagnostics: list[dict[str, str]], *, ref_key: str = "bom-ref") -> dict[str, Any] | None:
    name = _safe_text(raw.get("name"))
    version = _safe_text(raw.get("version")) or ""
    purl = _safe_text(raw.get("purl"), limit=2048) or ""
    ecosystem, purl_name, purl_version = _purl(purl)
    name = name or purl_name
    version = version or purl_version
    if not name:
        diagnostics.append(_diag("invalid_component", f"Component at {pointer} has no safe package name."))
        return None
    props = _properties_map(raw.get("properties"))
    ecosystem = str(props.get("ecosystem") or ecosystem or raw.get("type") or "unknown").lower()
    ref = _safe_text(raw.get(ref_key) or raw.get("SPDXID") or raw.get("spdxid"), limit=512) or _id("ref", ecosystem, name, version, pointer)
    manifest = props.get("codeslicer.manifest") or props.get("manifest")
    lockfile = props.get("codeslicer.lockfile") or props.get("lockfile")
    licenses: list[str] = []
    raw_licenses = raw.get("licenses") or []
    if isinstance(raw_licenses, list):
        for license_item in raw_licenses:
            if not isinstance(license_item, dict):
                continue
            license_data = license_item.get("license") if isinstance(license_item.get("license"), dict) else license_item
            value = _safe_text((license_data or {}).get("id") or (license_data or {}).get("name"))
            if value and value not in licenses:
                licenses.append(value)
    license_value = _safe_text(raw.get("licenseDeclared") or raw.get("licenseConcluded"))
    if license_value and license_value not in licenses:
        licenses.append(license_value)
    return {
        "ref": ref, "name": name, "version": version, "ecosystem": ecosystem,
        "purl": purl, "manifest": manifest, "lockfile": lockfile,
        "licenses": licenses[:20], "scope": _safe_text(raw.get("scope")),
        "pointer": pointer,
    }


def _tool_metadata(document: dict[str, Any], format_name: str) -> dict[str, Any]:
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    tools = metadata.get("tools") if isinstance(metadata.get("tools"), list) else []
    if tools and isinstance(tools[0], dict):
        tool = tools[0]
        return {"name": _safe_text(tool.get("name")) or format_name, "version": _safe_text(tool.get("version"))}
    creation = document.get("creationInfo") if isinstance(document.get("creationInfo"), dict) else {}
    return {"name": _safe_text(creation.get("createdBy")) or format_name, "version": None, "timestamp": _safe_text(creation.get("created"))}


def _cyclonedx(document: dict[str, Any], diagnostics: list[dict[str, str]]) -> dict[str, Any]:
    version = str(document.get("specVersion") or "")
    if not version.startswith("1.") or document.get("bomFormat") != "CycloneDX":
        return {"format": None, "diagnostics": [_diag("unsupported_format", "Expected a CycloneDX JSON BOM with specVersion 1.x.", "error")]}
    components: list[dict[str, Any]] = []
    for index, raw in enumerate(document.get("components") or []):
        if isinstance(raw, dict) and len(components) < MAX_SECURITY_ITEMS:
            item = _component(raw, f"#/components/{index}", diagnostics)
            if item:
                components.append(item)
    if len(document.get("components") or []) > MAX_SECURITY_ITEMS:
        diagnostics.append(_diag("item_limit", f"CycloneDX components were bounded at {MAX_SECURITY_ITEMS}.", "error"))
    relations: list[tuple[str, str, str]] = []
    for index, raw in enumerate(document.get("dependencies") or []):
        if not isinstance(raw, dict):
            continue
        parent = _safe_text(raw.get("ref"))
        for child in raw.get("dependsOn") or []:
            child_ref = _safe_text(child)
            if parent and child_ref:
                relations.append((parent, child_ref, f"#/dependencies/{index}"))
    findings: list[dict[str, Any]] = []
    for index, raw in enumerate(document.get("vulnerabilities") or []):
        if not isinstance(raw, dict):
            continue
        finding_id = _safe_text(raw.get("id")) or _id("finding", index)
        ratings = raw.get("ratings") if isinstance(raw.get("ratings"), list) else []
        severity = _safe_text((ratings[0] if ratings and isinstance(ratings[0], dict) else {}).get("severity")) or "unknown"
        affects = [_safe_text(item.get("ref")) for item in raw.get("affects") or [] if isinstance(item, dict) and _safe_text(item.get("ref"))]
        findings.append({"id": finding_id, "severity": severity.lower(), "refs": affects[:100], "rule_id": finding_id, "pointer": f"#/vulnerabilities/{index}"})
    return {"format": "cyclonedx", "version": version, "components": components, "relations": relations, "findings": findings, "tool": _tool_metadata(document, "CycloneDX"), "timestamp": _safe_text((document.get("metadata") or {}).get("timestamp")) if isinstance(document.get("metadata"), dict) else None}


def _spdx(document: dict[str, Any], diagnostics: list[dict[str, str]]) -> dict[str, Any]:
    version = str(document.get("spdxVersion") or "")
    if not version.startswith("SPDX-2."):
        return {"format": None, "diagnostics": [_diag("unsupported_format", "Expected an SPDX JSON document with spdxVersion 2.x.", "error")]}
    files = {str(item.get("SPDXID")): _safe_text(item.get("fileName"), limit=2048) for item in document.get("files") or [] if isinstance(item, dict) and item.get("SPDXID")}
    components: list[dict[str, Any]] = []
    for index, raw in enumerate(document.get("packages") or []):
        if not isinstance(raw, dict) or len(components) >= MAX_SECURITY_ITEMS:
            continue
        external = raw.get("externalRefs") if isinstance(raw.get("externalRefs"), list) else []
        purl = next((_safe_text(item.get("referenceLocator"), limit=2048) for item in external if isinstance(item, dict) and item.get("referenceType") == "purl"), "")
        enriched = {**raw, "purl": purl, "pointer": f"#/packages/{index}"}
        item = _component(enriched, f"#/packages/{index}", diagnostics, ref_key="SPDXID")
        if item:
            item["manifest"] = item.get("manifest") or _safe_text(raw.get("packageFileName"), limit=2048)
            components.append(item)
    relations: list[tuple[str, str, str]] = []
    for index, raw in enumerate(document.get("relationships") or []):
        if not isinstance(raw, dict):
            continue
        relation = str(raw.get("relationshipType") or "")
        source = _safe_text(raw.get("spdxElementId"))
        target = _safe_text(raw.get("relatedSpdxElement"))
        if relation == "DEPENDS_ON" and source and target:
            relations.append((source, target, f"#/relationships/{index}"))
        if relation == "CONTAINS" and source and target and target in files and files[target] and ("lock" in files[target].lower() or "manifest" in files[target].lower() or Path(files[target]).name in {"package.json", "requirements.txt", "packages.lock.json", "poetry.lock"}):
            component = next((item for item in components if item["ref"] == source), None)
            if component:
                component["manifest"] = files[target]
    return {"format": "spdx", "version": version, "components": components, "relations": relations, "findings": [], "tool": _tool_metadata(document, "SPDX"), "timestamp": _safe_text((document.get("creationInfo") or {}).get("created")) if isinstance(document.get("creationInfo"), dict) else None}


def _sarif_severity(result: dict[str, Any]) -> str:
    level = str(result.get("level") or "warning").lower()
    return {"error": "high", "warning": "medium", "note": "low", "none": "info"}.get(level, level)


def _range_norm(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    aliases = {
        "start_line": ("start_line", "startLine"),
        "start_column": ("start_column", "startColumn"),
        "end_line": ("end_line", "endLine"),
        "end_column": ("end_column", "endColumn"),
    }
    return {key: value[source] for key, names in aliases.items() for source in names if value.get(source) is not None}


def _sarif(document: dict[str, Any], diagnostics: list[dict[str, str]]) -> dict[str, Any]:
    if str(document.get("version") or "") != "2.1.0" or not isinstance(document.get("runs"), list):
        return {"format": None, "diagnostics": [_diag("unsupported_format", "Expected SARIF version 2.1.0 with runs.", "error")]}
    findings: list[dict[str, Any]] = []
    for run_index, run in enumerate(document.get("runs") or []):
        if not isinstance(run, dict):
            continue
        driver = ((run.get("tool") or {}).get("driver") or {}) if isinstance(run.get("tool"), dict) else {}
        tool = {"name": _safe_text(driver.get("name")) or "SARIF", "version": _safe_text(driver.get("version"))}
        for result_index, raw in enumerate(run.get("results") or []):
            if not isinstance(raw, dict):
                continue
            rule_id = _safe_text(raw.get("ruleId")) or "unknown-rule"
            locations: list[dict[str, Any]] = []
            for location_index, location in enumerate(raw.get("locations") or []):
                if not isinstance(location, dict):
                    continue
                physical = location.get("physicalLocation") or {}
                uri = _safe_uri((physical.get("artifactLocation") or {}).get("uri"), diagnostics, f"#/runs/{run_index}/results/{result_index}/locations/{location_index}")
                region = physical.get("region") if isinstance(physical.get("region"), dict) else {}
                if not uri:
                    continue
                normalized_range = _range_norm(region)
                complete = all(key in normalized_range for key in ("start_line", "start_column", "end_line", "end_column"))
                if not complete:
                    diagnostics.append(_diag("incomplete_range", f"SARIF location for {rule_id} has no complete range."))
                locations.append({"file": uri, "range": normalized_range, "complete": complete, "pointer": f"#/runs/{run_index}/results/{result_index}/locations/{location_index}"})
            findings.append({"id": _id("sarif", run_index, result_index, rule_id), "rule_id": rule_id, "severity": _sarif_severity(raw), "locations": locations[:20], "pointer": f"#/runs/{run_index}/results/{result_index}", "tool": tool})
    return {"format": "sarif", "version": "2.1.0", "components": [], "relations": [], "findings": findings, "tool": tool if 'tool' in locals() else {"name": "SARIF", "version": None}}


def parse_security_report(path: str | Path, adapter_id: str) -> dict[str, Any]:
    source = Path(path).resolve()
    document, diagnostics = _read_report(source)
    if not document:
        return {"format": None, "components": [], "relations": [], "findings": [], "diagnostics": diagnostics, "summary": {"components": 0, "dependencies": 0, "findings": 0, "licenses": 0, "severity": {}}}
    if adapter_id == "cyclonedx":
        parsed = _cyclonedx(document, diagnostics)
    elif adapter_id == "spdx":
        parsed = _spdx(document, diagnostics)
    elif adapter_id == "sarif":
        parsed = _sarif(document, diagnostics)
    else:
        parsed = {"format": None, "diagnostics": [_diag("unsupported_adapter", f"Unsupported security adapter: {adapter_id}.", "error")]}
    diagnostics.extend(parsed.pop("diagnostics", []))
    components = parsed.get("components") or []
    findings = parsed.get("findings") or []
    severity: dict[str, int] = {}
    for finding in findings:
        value = str(finding.get("severity") or "unknown")
        severity[value] = severity.get(value, 0) + 1
    parsed.update({"adapter_id": adapter_id, "diagnostics": diagnostics, "summary": {
        "components": len(components), "dependencies": len(parsed.get("relations") or []),
        "findings": len(findings), "licenses": len({license_id for item in components for license_id in item.get("licenses") or []}),
        "severity": severity,
    }})
    return parsed


def _node(node_id: str, kind: str, name: str, **properties: Any) -> dict[str, Any]:
    return {"id": node_id, "kind": kind, "name": name, "properties": properties, "evidence_class": "SECURITY_FINDING", "observed": True}


def _edge(edge_id: str, source: str, target: str, kind: str, **properties: Any) -> dict[str, Any]:
    return {"id": edge_id, "from": source, "to": target, "kind": kind, "evidence_class": "SECURITY_FINDING", "confidence": "confirmed", "resolution": "confirmed", "confirmed": True, "properties": properties}


def _is_generated(path: str | None) -> bool:
    return bool(path and _GENERATED_PATH.search(path.replace("\\", "/")))


def build_security_overlay(parsed: dict[str, Any], artifact_path: str, *, adapter_id: str, project_root: str | Path | None = None, freshness: dict[str, Any] | None = None, enabled: bool = False) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    component_nodes: dict[str, str] = {}
    package_nodes: dict[str, str] = {}
    manifest_nodes: dict[str, str] = {}

    def add(item: dict[str, Any]) -> None:
        if item["id"] not in node_ids:
            nodes.append(item); node_ids.add(item["id"])

    for component in parsed.get("components") or []:
        ref = component["ref"]
        component_id = _id("component", adapter_id, ref)
        package_id = _id("package", adapter_id, component.get("ecosystem"), component.get("name"), component.get("version"), ref)
        component_nodes[ref] = component_id; package_nodes[ref] = package_id
        path = component.get("manifest") or component.get("lockfile")
        review_excluded = _is_generated(path)
        base = {"report_path": artifact_path, "report_pointer": component.get("pointer"), "bom_ref": ref, "ecosystem": component.get("ecosystem"), "package_name": component.get("name"), "version": component.get("version"), "purl": component.get("purl"), "manifest_path": component.get("manifest"), "lockfile_path": component.get("lockfile"), "review_entity": not review_excluded, "excluded_from_review": review_excluded}
        add(_node(component_id, "COMPONENT", component.get("name") or ref, **base))
        add(_node(package_id, "PACKAGE", component.get("name") or ref, **base))
        edges.append(_edge(_id("component-package", ref), component_id, package_id, "COMPONENT_PACKAGE", bom_ref=ref))
        version_id = _id("version", component.get("ecosystem"), component.get("name"), component.get("version"), ref)
        add(_node(version_id, "VERSION", component.get("version") or "unresolved", version=component.get("version") or None, package_name=component.get("name"), report_path=artifact_path, report_pointer=component.get("pointer")))
        edges.append(_edge(_id("package-version", ref), package_id, version_id, "PACKAGE_VERSION", bom_ref=ref))
        for license_id in component.get("licenses") or []:
            license_node_id = _id("license", license_id)
            add(_node(license_node_id, "LICENSE", license_id, license_id=license_id, report_path=artifact_path, report_pointer=component.get("pointer")))
            edges.append(_edge(_id("package-license", ref, license_id), package_id, license_node_id, "HAS_LICENSE", license_id=license_id))
        if path:
            role = "lockfile" if component.get("lockfile") else "manifest"
            manifest_id = manifest_nodes.setdefault(path, _id("manifest", path))
            add(_node(manifest_id, "MANIFEST", path, path=path, role=role, report_path=artifact_path, review_entity=not _is_generated(path)))
            edges.append(_edge(_id("declared", ref, path), package_id, manifest_id, "LOCKED_BY" if role == "lockfile" else "DECLARED_IN", path=path))
    for source, target, pointer in parsed.get("relations") or []:
        if source not in package_nodes or target not in package_nodes:
            continue
        dependency_id = _id("dependency", source, target, pointer)
        add(_node(dependency_id, "DEPENDENCY", f"{source} → {target}", from_ref=source, to_ref=target, report_path=artifact_path, report_pointer=pointer))
        edges.append(_edge(_id("depends", source, target, pointer), package_nodes[source], package_nodes[target], "DEPENDS_ON", report_pointer=pointer))
    for finding in parsed.get("findings") or []:
        finding_id = _id("finding", adapter_id, finding.get("id"), finding.get("pointer"))
        add(_node(finding_id, "VULNERABILITY_FINDING", finding.get("id") or "finding", finding_id=finding.get("id"), rule_id=finding.get("rule_id"), severity=finding.get("severity"), report_path=artifact_path, report_pointer=finding.get("pointer"), tool=finding.get("tool") or parsed.get("tool")))
        for ref in finding.get("refs") or []:
            if ref in component_nodes:
                edges.append(_edge(_id("finding-component", finding_id, ref), finding_id, component_nodes[ref], "FINDING_AFFECTS_COMPONENT", finding_id=finding.get("id"), severity=finding.get("severity")))
        for location in finding.get("locations") or []:
            file_path = location.get("file")
            if not file_path:
                continue
            code_id = _id("code", file_path, json.dumps(location.get("range") or {}, sort_keys=True), finding.get("rule_id"))
            add(_node(code_id, "AFFECTED_FILE_RANGE", file_path, file=file_path, path=file_path, range=location.get("range") or {}, complete_range=bool(location.get("complete")), rule_id=finding.get("rule_id"), report_path=artifact_path, report_pointer=location.get("pointer"), review_entity=not _is_generated(file_path), excluded_from_review=_is_generated(file_path)))
            edges.append(_edge(_id("finding-code", finding_id, code_id), finding_id, code_id, "FINDING_POINTS_TO_CODE", rule_id=finding.get("rule_id"), complete_range=bool(location.get("complete"))))
    return {
        "schema_version": SECURITY_OVERLAY_SCHEMA, "adapter_id": adapter_id, "evidence_class": "SECURITY_FINDING", "confidence": "confirmed_if_exact", "freshness": freshness or {"status": "fresh", "verified": True}, "format": parsed.get("format"), "spec_version": parsed.get("version"), "source_report_path": artifact_path, "tool": parsed.get("tool") or {}, "timestamp": parsed.get("timestamp"), "nodes": nodes, "edges": edges, "diagnostics": list(parsed.get("diagnostics") or []), "summary": parsed.get("summary") or {}, "network_used": False, "privacy": {"mode": "local-only", "network_used": False, "raw_messages_stored": False, "secrets_stored": False, "redaction": "allowlist"}, "enabled": enabled, "project_root": str(project_root) if project_root else None,
    }


def _norm(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().lower().rstrip("/")


def _path_matches(report_path: Any, canonical_path: Any) -> bool:
    left, right = _norm(report_path), _norm(canonical_path)
    return bool(left and right and (left == right or left.endswith("/" + right) or right.endswith("/" + left)))


def _canonical_client_package(node: Any) -> dict[str, str]:
    props = node.properties or {}
    return {"name": _norm(props.get("package_name") or props.get("package") or props.get("dependency") or node.name), "version": _norm(props.get("version") or props.get("package_version")), "ecosystem": _norm(props.get("ecosystem") or props.get("package_manager")), "path": str(props.get("file") or props.get("path") or props.get("manifest") or props.get("lockfile") or "")}


def map_security_overlay(overlay: dict[str, Any], canonical_graph: GraphDocument) -> dict[str, Any]:
    result = copy.deepcopy(overlay)
    freshness = (result.get("freshness") or {}).get("status")
    for item in result.get("nodes", []):
        props = item.get("properties") or {}
        candidates: list[tuple[Any, str]] = []
        if item.get("kind") in {"PACKAGE", "COMPONENT"}:
            name, version, ecosystem = _norm(props.get("package_name") or item.get("name")), _norm(props.get("version")), _norm(props.get("ecosystem"))
            report_path = props.get("manifest_path") or props.get("lockfile_path")
            for node in canonical_graph.nodes:
                candidate = _canonical_client_package(node)
                if candidate["name"] != name:
                    continue
                if version and candidate["version"] == version and ecosystem and candidate["ecosystem"] == ecosystem and report_path and _path_matches(report_path, candidate["path"]):
                    candidates.append((node, "exact ecosystem + name + version + manifest/lockfile"))
                elif candidate["name"] == name and (not version or not candidate["version"]):
                    candidates.append((node, "package name without resolved version"))
        elif item.get("kind") == "AFFECTED_FILE_RANGE":
            file_path, rule_id, source_range = props.get("file"), _norm(props.get("rule_id")), _range_norm(props.get("range"))
            for node in canonical_graph.nodes:
                node_props = node.properties or {}
                node_range = _range_norm(node_props.get("range") or node_props.get("definition_range") or {})
                node_rule = _norm(node_props.get("rule_id") or node_props.get("security_rule_id"))
                node_file = node_props.get("file") or node_props.get("path")
                if file_path and _path_matches(file_path, node_file) and source_range and source_range == node_range and rule_id and node_rule == rule_id:
                    candidates.append((node, "exact SARIF file + complete range + rule ID"))
                elif file_path and _path_matches(file_path, node_file):
                    candidates.append((node, "file match without complete rule/range evidence"))
        else:
            name = _norm(item.get("name"))
            candidates = [(node, "weak security candidate") for node in canonical_graph.nodes if name and name == _norm(node.name)]
        exact = [pair for pair in candidates if pair[1].startswith("exact")]
        if len(exact) == 1:
            node, strategy = exact[0]
            item["mapping"] = {"status": "stale" if freshness in {"stale", "unverified"} else "confirmed", "strategy": strategy, "canonical_node_id": None if freshness in {"stale", "unverified"} else node.id}
            item["confidence"] = "stale" if freshness in {"stale", "unverified"} else "confirmed"
        elif len(exact) > 1:
            item["mapping"] = {"status": "unresolved", "strategy": "ambiguous exact candidates", "canonical_node_id": None}; item["confidence"] = "unresolved"
        elif candidates and len(candidates) == 1:
            item["mapping"] = {"status": "likely", "strategy": candidates[0][1], "canonical_node_id": None}; item["confidence"] = "likely"
        else:
            item["mapping"] = {"status": "unresolved", "strategy": "no exact security evidence", "canonical_node_id": None}; item["confidence"] = "unresolved"
    for edge in result.get("edges", []):
        source = next((node for node in result["nodes"] if node.get("id") == edge.get("from")), None)
        target = next((node for node in result["nodes"] if node.get("id") == edge.get("to")), None)
        if source and target and source.get("mapping", {}).get("status") == target.get("mapping", {}).get("status") == "confirmed":
            edge["resolution"] = "confirmed"
        elif source and target and source.get("mapping", {}).get("status") in {"confirmed", "likely"} and target.get("mapping", {}).get("status") in {"confirmed", "likely"}:
            edge.update({"resolution": "likely", "confirmed": False, "confidence": "likely"})
        else:
            edge.update({"resolution": "unresolved", "confirmed": False, "confidence": "unresolved"})
    result["mapping_summary"] = {key: sum(1 for node in result.get("nodes", []) if node.get("mapping", {}).get("status") == key) for key in ("confirmed", "likely", "unresolved", "stale")}
    return result
