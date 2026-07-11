"""Project Inventory models. Stage 12."""
from dataclasses import dataclass, field
from typing import List


@dataclass
class ProjectInventory:
    root_path: str
    files: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    package_manifests: List[str] = field(default_factory=list)
    declared_dependencies: List[str] = field(default_factory=list)
    external_imports: List[str] = field(default_factory=list)
    local_modules: List[str] = field(default_factory=list)
    declared_dependencies_by_ecosystem: dict[str, List[str]] = field(default_factory=dict)
    dev_dependencies_by_ecosystem: dict[str, List[str]] = field(default_factory=dict)
    external_imports_by_ecosystem: dict[str, List[str]] = field(default_factory=dict)
    local_modules_by_ecosystem: dict[str, List[str]] = field(default_factory=dict)
    files_count: int = 0
    classes_count: int = 0
    methods_count: int = 0
    loc: int = 0

    def to_dict(self) -> dict:
        return {
            "root_path": self.root_path,
            "files": self.files,
            "files_count": self.files_count if self.files_count else len(self.files),
            "classes_count": self.classes_count,
            "methods_count": self.methods_count,
            "loc": self.loc,
            "languages": self.languages,
            "package_manifests": self.package_manifests,
            "declared_dependencies": self.declared_dependencies,
            "external_imports": self.external_imports,
            "local_modules": self.local_modules,
            "declared_dependencies_by_ecosystem": self.declared_dependencies_by_ecosystem,
            "dev_dependencies_by_ecosystem": self.dev_dependencies_by_ecosystem,
            "external_imports_by_ecosystem": self.external_imports_by_ecosystem,
            "local_modules_by_ecosystem": self.local_modules_by_ecosystem
        }
