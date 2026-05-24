"""Wikidata based ontology expansion toolkit."""

from __future__ import annotations

from .models import ChangeSet, ExpansionConfig

__all__ = ["ChangeSet", "ExpansionConfig", "ExpansionEngine"]


def __getattr__(name: str):
    if name == "ExpansionEngine":
        from .engine import ExpansionEngine

        return ExpansionEngine
    raise AttributeError(name)
