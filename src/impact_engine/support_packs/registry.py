"""Support pack registry implementation. Stage 8 complete."""
import shutil
import json
from pathlib import Path
from typing import List, Optional
from impact_engine.support_packs.schema import SupportPack, support_pack_from_dict, validate_support_pack_dict


def list_local_support_packs(root: str | Path = "support_packs") -> List[Path]:
    base = Path(root)
    if not base.exists():
        return []
    paths = []
    for path in base.glob("**/support_pack.json"):
        try:
            relative_parts = path.relative_to(base).parts
        except ValueError:
            relative_parts = path.parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        paths.append(path)
    return sorted(paths)


def load_support_pack(pack_path: str | Path) -> SupportPack:
    pack_path = Path(pack_path)
    data = json.loads(pack_path.read_text(encoding="utf-8"))
    return support_pack_from_dict(data)


def load_support_pack_dict(pack_path: str | Path) -> dict:
    return json.loads(Path(pack_path).read_text(encoding="utf-8"))


def validate_support_pack_file(pack_path: str | Path) -> dict:
    pack_path = Path(pack_path)
    try:
        data = json.loads(pack_path.read_text(encoding="utf-8"))
        errors = validate_support_pack_dict(data)
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "library": data.get("library") if isinstance(data, dict) else None,
            "path": str(pack_path.as_posix())
        }
    except Exception as e:
        return {
            "valid": False,
            "errors": [str(e)],
            "library": None,
            "path": str(pack_path.as_posix())
        }


def find_support_pack(library: str, root: str | Path = "support_packs") -> Optional[Path]:
    candidates = list_local_support_packs(root)
    for path in candidates:
        val_res = validate_support_pack_file(path)
        if val_res["valid"] and val_res["library"] == library:
            return path
    return None


def import_support_pack_file(pack_path: str | Path, registry_root: str | Path = "support_packs") -> dict:
    pack_path = Path(pack_path)
    registry_root = Path(registry_root)
    
    val_res = validate_support_pack_file(pack_path)
    if not val_res["valid"]:
        return {
            "status": "error",
            "errors": val_res["errors"],
            "message": "Source support pack is invalid."
        }
        
    library = val_res["library"]
    target_dir = registry_root / library
    target_path = target_dir / "support_pack.json"
    
    try:
        same_path = target_path.resolve() == pack_path.resolve()
    except Exception:
        same_path = False
        
    if same_path:
        return {
            "status": "already_exists",
            "path": str(target_path.as_posix()),
            "message": "Support pack already exists in registry."
        }
        
    if target_path.exists():
        return {
            "status": "already_exists",
            "path": str(target_path.as_posix()),
            "message": f"Support pack for '{library}' already exists in registry."
        }
        
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pack_path, target_path)
        return {
            "status": "imported",
            "path": str(target_path.as_posix()),
            "message": f"Successfully imported support pack for '{library}'."
        }
    except Exception as e:
        return {
            "status": "error",
            "errors": [str(e)],
            "message": f"Failed to copy support pack: {str(e)}"
        }
