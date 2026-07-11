from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .facts import FactSet
from .models import ClassFact, FunctionFact, Symbol


class SymbolTable:
    """Small deterministic symbol table over normalized facts."""

    def __init__(self) -> None:
        self._by_name: Dict[str, Symbol] = {}
        self._by_qualified: Dict[str, Symbol] = {}

    def register(self, symbol: Symbol) -> None:
        self._by_name.setdefault(symbol.name, symbol)
        if symbol.qualified_name:
            self._by_qualified[symbol.qualified_name] = symbol

    def lookup(self, name: str) -> Optional[Symbol]:
        if name in self._by_qualified:
            return self._by_qualified[name]
        if name in self._by_name:
            return self._by_name[name]
        matches = [s for q, s in self._by_qualified.items() if q.endswith(f".{name}")]
        if len(matches) == 1:
            return matches[0]
        return None

    def symbols(self) -> List[Symbol]:
        seen = {s.id: s for s in list(self._by_qualified.values()) + list(self._by_name.values())}
        return sorted(seen.values(), key=lambda s: s.id or "")

    @classmethod
    def from_facts(cls, facts: FactSet) -> "SymbolTable":
        table = cls()
        for symbol in facts.symbols:
            table.register(symbol)
        for fn in facts.functions:
            table.register(Symbol(name=fn.name, qualified_name=fn.qualified_name, kind="function", file=fn.file, line=fn.line))
        for klass in facts.classes:
            table.register(Symbol(name=klass.name, qualified_name=klass.qualified_name, kind="class", file=klass.file, line=klass.line, type_name=klass.name))
            for method in klass.methods:
                table.register(Symbol(name=f"{klass.name}.{method}", qualified_name=f"{klass.qualified_name}.{method}", kind="method", file=klass.file, line=klass.line))
        return table
