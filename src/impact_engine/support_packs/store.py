"""Support Pack Store implementation. Stage 12."""
import json
from pathlib import Path
from typing import List, Optional
from impact_engine.support_packs.schema import SupportPack, support_pack_from_dict, validate_support_pack_dict, support_pack_to_dict
from impact_engine.support_packs.registry import list_local_support_packs, load_support_pack


class SupportPackStore:
    def __init__(self, root: str | Path = "support_packs"):
        self.root = Path(root)

    def list_packs(self) -> List[SupportPack]:
        paths = list_local_support_packs(self.root)
        packs = []
        for p in paths:
            try:
                packs.append(load_support_pack(p))
            except Exception:
                pass
        return packs

    def get_pack(self, ecosystem: str, library_name: str, version_range: str | None = None) -> Optional[SupportPack]:
        # 1. New layout lookup: root / ecosystem / library_name / support_pack.json
        p_new = self.root / ecosystem.lower() / library_name.lower() / "support_pack.json"
        if p_new.exists():
            try:
                return load_support_pack(p_new)
            except Exception:
                pass

        # 2. Backward-compatible layout lookup: root / library_name / support_pack.json
        p_old = self.root / library_name.lower() / "support_pack.json"
        if p_old.exists():
            try:
                pack = load_support_pack(p_old)
                if pack.language.lower() == ecosystem.lower():
                    return pack
            except Exception:
                pass

        # 3. Dynamic lookup in all registry paths
        for pack in self.list_packs():
            if pack.library.lower() == library_name.lower() and pack.language.lower() == ecosystem.lower():
                return pack
        return None

    def save_pack(self, pack: SupportPack) -> Path:
        ecosystem = pack.language.lower()
        library = pack.library.lower()
        dest_dir = self.root / ecosystem / library
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / "support_pack.json"
        
        dest_file.write_text(json.dumps(support_pack_to_dict(pack), indent=2), encoding="utf-8")
        return dest_file

    def validate_and_save_pack(self, pack_dict: dict) -> dict:
        errors = validate_support_pack_dict(pack_dict)
        if errors:
            return {"valid": False, "errors": errors, "path": None}
        
        try:
            pack = support_pack_from_dict(pack_dict)
            saved_path = self.save_pack(pack)
            return {"valid": True, "errors": [], "path": str(saved_path.as_posix())}
        except Exception as e:
            return {"valid": False, "errors": [str(e)], "path": None}

    def find_by_import(self, import_name: str) -> Optional[SupportPack]:
        # Checks if any pack library name matches the import name
        for pack in self.list_packs():
            if pack.library.lower() == import_name.lower():
                return pack
        return None
