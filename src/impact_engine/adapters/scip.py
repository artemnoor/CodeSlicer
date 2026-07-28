"""Optional local SCIP semantic-index adapter.

The importer supports the real SCIP protobuf wire format with a deliberately
small dependency-free decoder for the stable Index/Document/Occurrence/
SymbolInformation subset.  The documented JSON interchange remains available
for deterministic fixtures and backward compatibility.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from impact_engine.adapters.contracts import EVIDENCE_OVERLAY_SCHEMA_VERSION, normalize_overlay
from impact_engine.models import GraphDocument


SCIP_INTERCHANGE_SCHEMA = "CodeSlicerScipInterchange/v1"


def parse_scip_artifact(path: str | Path) -> dict[str, Any]:
    """Parse JSON interchange or a real binary SCIP protobuf artifact."""
    path = Path(path)
    raw = path.read_bytes()
    if not raw.lstrip().startswith(b"{"):
        return _parse_binary_scip(raw)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("SCIP interchange must be a JSON object")
    if data.get("schema_version") not in {None, SCIP_INTERCHANGE_SCHEMA}:
        raise ValueError(f"unsupported SCIP interchange schema: {data.get('schema_version')}")
    documents = data.get("documents")
    if not isinstance(documents, list):
        raise ValueError("SCIP interchange requires a documents array")
    index = data.get("index") or data.get("metadata") or {}
    symbols: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    normalized_documents: list[dict[str, Any]] = []

    def symbol_entry(symbol_id: str, name: str = "", kind: str = "symbol") -> dict[str, Any]:
        return symbols.setdefault(symbol_id, {
            "symbol_id": symbol_id, "name": name or symbol_id, "kind": kind or "symbol",
            "definitions": [], "references": [], "implementations": [],
        })

    for document in documents:
        if not isinstance(document, dict):
            diagnostics.append({"code": "invalid_document", "severity": "warning", "message": "SCIP document is not an object"})
            continue
        file_path = str(document.get("relative_path") or document.get("path") or "").replace("\\", "/")
        if not file_path:
            diagnostics.append({"code": "missing_source_file", "severity": "warning", "message": "SCIP document has no source file"})
            continue
        normalized_document = {
            "relative_path": file_path,
            "language": document.get("language"),
            "position_encoding": document.get("position_encoding"),
            "occurrences": [],
        }
        document_symbols = {str(item.get("symbol")): item for item in (document.get("symbols") or []) if isinstance(item, dict) and item.get("symbol")}
        for occurrence in document.get("occurrences") or []:
            if not isinstance(occurrence, dict) or not occurrence.get("symbol"):
                diagnostics.append({"code": "invalid_occurrence", "severity": "warning", "file": file_path})
                continue
            symbol_id = str(occurrence["symbol"])
            details = document_symbols.get(symbol_id, {})
            entry = symbol_entry(symbol_id, str(occurrence.get("symbol_name") or details.get("display_name") or _display_name(symbol_id)), str(occurrence.get("kind") or details.get("kind") or "symbol"))
            item = {
                "file": file_path,
                "range": _normalize_range(occurrence.get("range")),
                "role": _occurrence_role(occurrence),
                "enclosing_symbol": occurrence.get("enclosing_symbol") or occurrence.get("container_symbol"),
            }
            normalized_document["occurrences"].append(item)
            if item["role"] == "definition":
                entry["definitions"].append(item)
            else:
                entry["references"].append(item)
        for symbol_id, details in document_symbols.items():
            entry = symbol_entry(symbol_id, str(details.get("display_name") or _display_name(symbol_id)), str(details.get("kind") or "symbol"))
            for relationship in details.get("relationships") or []:
                if not isinstance(relationship, dict) or not relationship.get("symbol"):
                    continue
                if relationship.get("is_implementation") or str(relationship.get("kind") or "").lower() in {"implementation", "implements"}:
                    entry["implementations"].append({"symbol_id": str(relationship["symbol"]), "kind": "implementation"})
        normalized_documents.append(normalized_document)

    return {
        "schema_version": SCIP_INTERCHANGE_SCHEMA,
        "format": "json-interchange",
        "index_metadata": {
            "tool": index.get("tool") or index.get("tool_name"),
            "version": index.get("version"),
            "commit": index.get("commit") or index.get("revision"),
            "created_at": index.get("created_at"),
            "project_root": index.get("project_root"),
        },
        "symbols": list(symbols.values()),
        "documents": normalized_documents,
        "diagnostics": diagnostics,
    }


class _ProtoReader:
    """Minimal protobuf reader for the SCIP messages used by the adapter."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def varint(self) -> int:
        value = 0
        shift = 0
        while self.pos < len(self.data):
            byte = self.data[self.pos]
            self.pos += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7
            if shift > 70:
                raise ValueError("invalid protobuf varint")
        raise ValueError("truncated protobuf varint")

    def fields(self) -> dict[int, list[tuple[int, int | bytes]]]:
        result: dict[int, list[tuple[int, int | bytes]]] = {}
        while self.pos < len(self.data):
            key = self.varint()
            number, wire = key >> 3, key & 7
            if number == 0:
                raise ValueError("invalid protobuf field number 0")
            if wire == 0:
                value: int | bytes = self.varint()
            elif wire == 1:
                self._require(8)
                self.pos += 8
                continue
            elif wire == 2:
                length = self.varint()
                self._require(length)
                value = self.data[self.pos:self.pos + length]
                self.pos += length
            elif wire == 5:
                self._require(4)
                self.pos += 4
                continue
            else:
                raise ValueError(f"unsupported protobuf wire type {wire}")
            result.setdefault(number, []).append((wire, value))
        return result

    def _require(self, length: int) -> None:
        if length < 0 or self.pos + length > len(self.data):
            raise ValueError("truncated protobuf message")


def _proto_fields(data: bytes) -> dict[int, list[tuple[int, int | bytes]]]:
    return _ProtoReader(data).fields()


def _proto_bytes(fields: dict[int, list[tuple[int, int | bytes]]], number: int) -> list[bytes]:
    return [value for wire, value in fields.get(number, []) if wire == 2 and isinstance(value, bytes)]


def _proto_text(fields: dict[int, list[tuple[int, int | bytes]]], number: int) -> str | None:
    values = _proto_bytes(fields, number)
    if not values:
        return None
    try:
        return values[-1].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("SCIP protobuf contains invalid UTF-8 text") from exc


def _proto_int(fields: dict[int, list[tuple[int, int | bytes]]], number: int, default: int = 0) -> int:
    values = [value for wire, value in fields.get(number, []) if wire == 0 and isinstance(value, int)]
    return int(values[-1]) if values else default


def _proto_packed_ints(fields: dict[int, list[tuple[int, int | bytes]]], number: int) -> list[int]:
    values: list[int] = []
    for wire, value in fields.get(number, []):
        if wire == 0 and isinstance(value, int):
            values.append(value)
        elif wire == 2 and isinstance(value, bytes):
            reader = _ProtoReader(value)
            while reader.pos < len(value):
                values.append(reader.varint())
    return values


def _message_range(data: bytes, *, zero_based: bool, multiline: bool) -> dict[str, int] | None:
    fields = _proto_fields(data)
    line = _proto_int(fields, 1)
    start = _proto_int(fields, 2)
    end_line = _proto_int(fields, 3, line) if multiline else line
    end = _proto_int(fields, 4, _proto_int(fields, 3, start))
    if zero_based:
        line += 1
        end_line += 1
    return {"start_line": line, "start_column": start, "end_line": end_line, "end_column": end}


_SCIP_KIND_NAMES = {
    7: "class", 17: "function", 21: "interface", 26: "method", 29: "module",
    30: "namespace", 41: "property", 42: "protocol", 49: "struct", 54: "type",
    61: "variable", 16: "file", 37: "parameter", 46: "signature",
}


def _symbol_kind_from_id(symbol_id: str) -> str:
    """Infer a conservative kind when older official indexers omit Kind."""
    if symbol_id.startswith("local "):
        return "symbol"
    tail = symbol_id.rstrip("/").rsplit("/", 1)[-1]
    if "#" in tail:
        owner, member = tail.rsplit("#", 1)
        if member.endswith("().") or member.endswith("."):
            return "function" if owner.endswith((".py", ".ts", ".tsx", ".js", ".jsx")) else "method"
        if member:
            return "symbol"
        return "class"
    if tail.endswith("()."):
        return "function"
    if tail.endswith("."):
        return "variable"
    return "module"


def _binary_occurrence(data: bytes) -> dict[str, Any]:
    fields = _proto_fields(data)
    old_range = _proto_packed_ints(fields, 1)
    single_line = _proto_bytes(fields, 8)
    multi_line = _proto_bytes(fields, 9)
    typed = single_line or multi_line
    if typed:
        source_range = _message_range(typed[0], zero_based=True, multiline=bool(multi_line))
        range_encoding = "multi_line_typed" if multi_line else "single_line_typed"
    elif len(old_range) in {3, 4}:
        if len(old_range) == 3:
            old_range = [old_range[0], old_range[1], old_range[0], old_range[2]]
        source_range = {"start_line": old_range[0] + 1, "start_column": old_range[1], "end_line": old_range[2] + 1, "end_column": old_range[3]}
        range_encoding = "legacy_packed"
    else:
        source_range = None
        range_encoding = "missing"
    roles = _proto_int(fields, 3)
    return {
        "symbol": _proto_text(fields, 2) or "",
        "range": source_range,
        "role": "definition" if roles & 0x41 else "reference",
        "symbol_roles": roles,
        "range_encoding": range_encoding,
    }


def _binary_relationship(data: bytes) -> dict[str, Any]:
    fields = _proto_fields(data)
    return {
        "symbol": _proto_text(fields, 1) or "",
        "is_reference": bool(_proto_int(fields, 2)),
        "is_implementation": bool(_proto_int(fields, 3)),
        "is_definition": bool(_proto_int(fields, 5)),
    }


def _binary_symbol(data: bytes) -> dict[str, Any]:
    fields = _proto_fields(data)
    relationships = [_binary_relationship(item) for item in _proto_bytes(fields, 4)]
    symbol_id = _proto_text(fields, 1) or ""
    return {
        "symbol": symbol_id,
        "display_name": _proto_text(fields, 6) or _display_name(symbol_id),
        "kind": _SCIP_KIND_NAMES.get(_proto_int(fields, 5), "symbol"),
        "relationships": relationships,
        "enclosing_symbol": _proto_text(fields, 8),
    }


def _parse_binary_scip(raw: bytes) -> dict[str, Any]:
    """Decode the standard SCIP Index protobuf without a third-party runtime."""
    if not raw or not raw.strip():
        raise ValueError("empty SCIP protobuf artifact")
    try:
        fields = _proto_fields(raw)
        metadata_fields = _proto_fields(_proto_bytes(fields, 1)[0]) if _proto_bytes(fields, 1) else {}
        tool_fields = _proto_fields(_proto_bytes(metadata_fields, 2)[0]) if _proto_bytes(metadata_fields, 2) else {}
        index_metadata = {
            "format": "binary-protobuf",
            "protocol_version": _proto_int(metadata_fields, 1),
            "project_root": _proto_text(metadata_fields, 3),
            "text_encoding": _proto_int(metadata_fields, 4),
            "tool": _proto_text(tool_fields, 1),
            "version": _proto_text(tool_fields, 2),
        }
        documents: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for document_raw in _proto_bytes(fields, 2):
            document_fields = _proto_fields(document_raw)
            file_path = _proto_text(document_fields, 1) or ""
            file_path = file_path.replace("\\", "/")
            if not file_path or file_path.startswith("/") or ".." in file_path.split("/"):
                diagnostics.append({"code": "invalid_relative_path", "severity": "warning", "file": file_path})
                continue
            symbols = [_binary_symbol(item) for item in _proto_bytes(document_fields, 3)]
            for symbol in symbols:
                if symbol.get("kind") == "symbol":
                    symbol["kind"] = _symbol_kind_from_id(str(symbol.get("symbol") or ""))
            symbol_by_id = {item["symbol"]: item for item in symbols if item["symbol"]}
            occurrences = []
            for occurrence_raw in _proto_bytes(document_fields, 2):
                occurrence = _binary_occurrence(occurrence_raw)
                details = symbol_by_id.get(occurrence["symbol"], {})
                occurrence["symbol_name"] = details.get("display_name") or _display_name(occurrence["symbol"])
                occurrence["kind"] = details.get("kind", "symbol")
                occurrence["enclosing_symbol"] = details.get("enclosing_symbol")
                occurrences.append(occurrence)
            documents.append({
                "relative_path": file_path,
                "language": _proto_text(document_fields, 4),
                "position_encoding": _proto_int(document_fields, 6),
                "symbols": symbols,
                "occurrences": occurrences,
            })
        normalized = _normalize_documents(documents, index_metadata, diagnostics)
        normalized["format"] = "binary-protobuf"
        return normalized
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"invalid binary SCIP protobuf: {exc}") from exc


def _normalize_documents(documents: list[dict[str, Any]], index: dict[str, Any], diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    symbols: dict[str, dict[str, Any]] = {}

    def entry(symbol_id: str, name: str = "", kind: str = "symbol") -> dict[str, Any]:
        current = symbols.get(symbol_id)
        if current is None:
            current = {"symbol_id": symbol_id, "name": name or symbol_id, "kind": kind or "symbol", "definitions": [], "references": [], "implementations": []}
            symbols[symbol_id] = current
        elif current.get("kind") == "symbol" and kind and kind != "symbol":
            current["kind"] = kind
        if name and current.get("name") == symbol_id:
            current["name"] = name
        return current

    for document in documents:
        file_path = document["relative_path"]
        for symbol in document.get("symbols", []):
            current = entry(symbol["symbol"], symbol.get("display_name", ""), symbol.get("kind", "symbol"))
            for relationship in symbol.get("relationships", []):
                target = relationship.get("symbol")
                if not target:
                    continue
                if relationship.get("is_implementation"):
                    current["implementations"].append({"symbol_id": target, "kind": "implementation"})
                elif relationship.get("is_reference"):
                    current["references"].append({"symbol_id": target, "relationship": "reference"})
        for occurrence in document.get("occurrences", []):
            current = entry(occurrence["symbol"], occurrence.get("symbol_name", ""), occurrence.get("kind", "symbol"))
            item = {"file": file_path, "range": occurrence.get("range"), "role": occurrence.get("role", "reference"), "enclosing_symbol": occurrence.get("enclosing_symbol")}
            if item["role"] == "definition":
                current["definitions"].append(item)
            else:
                current["references"].append(item)
    return {"schema_version": SCIP_INTERCHANGE_SCHEMA, "index_metadata": index, "documents": documents, "symbols": list(symbols.values()), "diagnostics": diagnostics}


def build_scip_overlay(
    data: dict[str, Any], *, artifact_path: str, project_root: str | Path,
    freshness: dict[str, Any] | None = None, enabled: bool = False,
) -> dict[str, Any]:
    symbols = data.get("symbols") or []
    nodes: list[dict[str, Any]] = []
    symbol_node_ids: dict[str, str] = {}
    for item in symbols:
        symbol_id = str(item.get("symbol_id") or "")
        if not symbol_id:
            continue
        node_id = "scip:" + hashlib.sha256(symbol_id.encode("utf-8")).hexdigest()[:24]
        symbol_node_ids[symbol_id] = node_id
        nodes.append({
            "id": node_id, "name": str(item.get("name") or _display_name(symbol_id)),
            "kind": str(item.get("kind") or "symbol"),
            "semantic_id": symbol_id, "semantic_provider": "scip",
            "definitions": list(item.get("definitions") or []),
            "reference_ranges": list(item.get("references") or []),
            "implementation_symbols": list(item.get("implementations") or []),
            "mapping": {"status": "unresolved", "strategy": None, "canonical_node_id": None},
        })
    edges: list[dict[str, Any]] = []
    for item in symbols:
        source_id = symbol_node_ids.get(str(item.get("symbol_id") or ""))
        if not source_id:
            continue
        for index, reference in enumerate(item.get("references") or []):
            target_id = symbol_node_ids.get(str(reference.get("symbol_id") or ""))
            if reference.get("relationship") == "reference" and target_id:
                source_node = source_id
            else:
                target_id = target_id or source_id
                enclosing = str(reference.get("enclosing_symbol") or "")
                source_node = symbol_node_ids.get(enclosing)
            if not source_node:
                edges.append({"id": f"scip:unresolved-reference:{source_id}:{index}", "kind": "REFERENCES", "from": source_id, "to": target_id or source_id, "resolution": "unresolved", "confidence": "unresolved", "evidence_class": "SEMANTIC_INDEX", "confirmed": False, "diagnostic": "reference has no enclosing symbol"})
                continue
            edges.append({"id": f"scip:reference:{source_node}:{target_id}:{index}", "kind": "REFERENCES", "from": source_node, "to": target_id, "range": reference.get("range"), "resolution": "unresolved", "confidence": "unresolved", "evidence_class": "SEMANTIC_INDEX", "confirmed": False})
        for relationship in item.get("implementations") or []:
            target_id = symbol_node_ids.get(str(relationship.get("symbol_id") or ""))
            if target_id:
                edges.append({"id": f"scip:implements:{source_id}:{target_id}", "kind": "IMPLEMENTS", "from": source_id, "to": target_id, "resolution": "unresolved", "confidence": "unresolved", "evidence_class": "SEMANTIC_INDEX", "confirmed": False})
    overlay = normalize_overlay(
        adapter_id="scip", adapter_version="1.0", source_kind="SCIP_SEMANTIC_INDEX",
        evidence_class="SEMANTIC_INDEX", confidence="confirmed_if_fresh",
        freshness=freshness or {"status": "unverified", "verified": False},
        local_artifact_reference={"path": str(Path(artifact_path).resolve())},
        nodes=nodes, edges=edges,
        diagnostics=list(data.get("diagnostics") or []) + ([{"code": "json_interchange", "severity": "info", "message": "Using CodeSlicerScipInterchange/v1 JSON interchange."}] if data.get("format") != "binary-protobuf" else [{"code": "binary_protobuf_decoder", "severity": "info", "message": "Decoded standard SCIP protobuf with CodeSlicer local decoder."}]),
        enabled=enabled, availability="ready" if enabled else "disabled",
    )
    overlay["index_metadata"] = dict(data.get("index_metadata") or {})
    overlay["semantic_summary"] = {
        "symbols": len(nodes),
        "definitions": sum(len(item.get("definitions") or []) for item in symbols),
        "references": sum(len(item.get("references") or []) for item in symbols),
        "implementations": sum(len(item.get("implementations") or []) for item in symbols),
    }
    return overlay


def map_scip_overlay(overlay: dict[str, Any], canonical_graph: GraphDocument) -> dict[str, Any]:
    """Map semantic nodes conservatively; ambiguous/name-only matches stay unresolved."""
    result = dict(overlay)
    canonical = list(canonical_graph.nodes)
    freshness = (overlay.get("freshness") or {}).get("status")
    exact_count = ambiguous_count = unresolved_count = 0
    for node in result.get("nodes", []):
        definitions = node.get("definitions") or []
        candidates = []
        for candidate in canonical:
            if str(candidate.properties.get("semantic_id") or "") == str(node.get("semantic_id")):
                candidates.append((candidate, "stable semantic ID"))
        if not candidates:
            for definition in definitions:
                candidates = _exact_range_candidates(canonical, definition, node)
                if candidates:
                    break
        if len(candidates) == 1:
            canonical_node, strategy = candidates[0]
            exact_strategy = strategy in {"stable semantic ID", "exact source file + definition range + kind"}
            node["mapping"] = {"status": "confirmed" if freshness == "fresh" and exact_strategy else ("stale" if freshness != "fresh" else "unresolved"), "strategy": strategy, "canonical_node_id": canonical_node.id if exact_strategy else None}
            node["semantic_provider"] = "scip"
            node["definition_range"] = definitions[0].get("range") if definitions else None
            exact_count += 1
        elif len(candidates) > 1:
            node["mapping"] = {"status": "ambiguous", "strategy": "multiple candidates", "canonical_node_id": None}
            ambiguous_count += 1
        else:
            node["mapping"] = {"status": "unresolved", "strategy": "no exact semantic ID or file/range/kind match", "canonical_node_id": None}
            unresolved_count += 1
    node_by_id = {node.get("id"): node for node in result.get("nodes", [])}
    for edge in result.get("edges", []):
        source = node_by_id.get(edge.get("from"), {})
        target = node_by_id.get(edge.get("to"), {})
        source_map = source.get("mapping", {}).get("status")
        target_map = target.get("mapping", {}).get("status")
        if source_map == target_map == "confirmed" and freshness == "fresh":
            edge.update({"resolution": "confirmed", "confidence": "confirmed", "confirmed": True})
        elif source_map in {"confirmed", "stale"} and target_map in {"confirmed", "stale"}:
            edge.update({"resolution": "stale" if freshness != "fresh" else "likely", "confidence": "likely", "confirmed": False})
        else:
            edge.update({"resolution": "unresolved", "confidence": "unresolved", "confirmed": False})
    diagnostics = list(result.get("diagnostics") or [])
    if ambiguous_count:
        diagnostics.append({"code": "ambiguous_symbol_mapping", "severity": "warning", "count": ambiguous_count, "message": "Some SCIP symbols matched multiple CodeSlicer nodes"})
    if unresolved_count:
        diagnostics.append({"code": "unresolved_symbol_mapping", "severity": "info", "count": unresolved_count, "message": "Some SCIP symbols have no exact CodeSlicer mapping"})
    result["diagnostics"] = diagnostics
    result["mapping_summary"] = {"exact": exact_count, "ambiguous": ambiguous_count, "unresolved": unresolved_count}
    return result


def _normalize_range(value: Any) -> dict[str, int] | None:
    if isinstance(value, dict):
        try:
            return {"start_line": int(value.get("start_line", value.get("line", 0))), "start_column": int(value.get("start_column", value.get("column", 0))), "end_line": int(value.get("end_line", value.get("start_line", value.get("line", 0)))), "end_column": int(value.get("end_column", value.get("start_column", value.get("column", 0))))}
        except (TypeError, ValueError):
            return None
    if isinstance(value, list) and len(value) >= 2:
        numbers = [int(item) for item in value[:4]]
        while len(numbers) < 4:
            numbers.append(numbers[-1])
        return {"start_line": numbers[0], "start_column": numbers[1], "end_line": numbers[2], "end_column": numbers[3]}
    return None


def _occurrence_role(occurrence: dict[str, Any]) -> str:
    roles = occurrence.get("roles") or occurrence.get("role") or []
    values = roles if isinstance(roles, list) else [roles]
    text = " ".join(str(value).lower() for value in values)
    return "definition" if "definition" in text or text in {"def", "1"} else "reference"


def _display_name(symbol_id: str) -> str:
    if symbol_id.startswith("local "):
        return symbol_id
    tail = symbol_id.rstrip("/").rsplit("/", 1)[-1]
    if "#" in tail:
        owner, member = tail.rsplit("#", 1)
        tail = member or owner.rsplit("/", 1)[-1]
    if tail.endswith("()."):
        tail = tail[:-3]
    elif tail.endswith("."):
        tail = tail[:-1]
    if ".(" in tail:
        tail = tail.split(".(", 1)[-1].rstrip(")")
    tail = tail.strip("`")
    return tail or symbol_id


def _kind(value: Any) -> str:
    text = str(value or "").lower()
    return {"function": "FUNCTION", "method": "METHOD", "class": "CLASS", "interface": "CLASS", "module": "MODULE", "file": "FILE"}.get(text, text.upper() or "FUNCTION")


def _path_equal(left: Any, right: Any) -> bool:
    return str(left or "").replace("\\", "/").lstrip("./").lower() == str(right or "").replace("\\", "/").lstrip("./").lower()


def _exact_range_candidates(canonical: list[Any], definition: dict[str, Any], semantic_node: dict[str, Any]) -> list[tuple[Any, str]]:
    source_range = definition.get("range") or {}
    result = []
    for node in canonical:
        file_name = node.properties.get("file") or node.properties.get("path")
        if not _path_equal(file_name, definition.get("file")) or node.kind != _kind(semantic_node.get("kind")):
            continue
        line = node.properties.get("line")
        node_range = node.properties.get("definition_range") or {}
        range_line = node_range.get("start_line", line) if isinstance(node_range, dict) else line
        if not source_range or range_line is None or int(range_line) != int(source_range.get("start_line", -1)):
            continue
        source_column = source_range.get("start_column")
        node_column = node_range.get("start_column") if isinstance(node_range, dict) else node.properties.get("column")
        if source_column is not None and (node_column is None or int(source_column) != int(node_column)):
            continue
        source_end_line = source_range.get("end_line")
        node_end_line = node_range.get("end_line") if isinstance(node_range, dict) else None
        if source_end_line is not None and (node_end_line is None or int(source_end_line) != int(node_end_line)):
            continue
        source_end_column = source_range.get("end_column")
        node_end_column = node_range.get("end_column") if isinstance(node_range, dict) else None
        if source_end_column is not None and (node_end_column is None or int(source_end_column) != int(node_end_column)):
            continue
        if source_range:
            result.append((node, "exact source file + definition range + kind"))
    return result
