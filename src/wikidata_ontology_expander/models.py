from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SchemaField:
    owner: str
    section: str
    name: str
    label: str
    type_name: str
    module: str | None = None
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityType:
    name: str
    label: str
    kind: str
    domain: str | None = None
    fields: tuple[SchemaField, ...] = ()


@dataclass(frozen=True)
class SchemaConceptType:
    name: str
    label: str
    kind: str


@dataclass(frozen=True)
class SchemaModule:
    name: str
    domain: str
    kind: str
    entity_types: tuple[str, ...] = ()
    property_fields: tuple[str, ...] = ()
    relation_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class SchemaDomain:
    name: str
    key: str
    entity_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class SchemaDocument:
    concept_types: tuple[SchemaConceptType, ...]
    domains: tuple[SchemaDomain, ...]
    modules: tuple[SchemaModule, ...]
    entities: dict[str, EntityType]


@dataclass(frozen=True)
class SeedEntity:
    name: str
    entity_type: str
    qid: str | None = None
    aliases: tuple[str, ...] = ()
    module: str | None = None
    parent: str | None = None

    @property
    def search_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.name, *self.aliases)))


@dataclass(frozen=True)
class WikidataStatement:
    property_id: str
    property_label: str
    value_id: str | None
    value_label: str
    raw_value: Any = None


@dataclass(frozen=True)
class WikidataEntity:
    qid: str
    label: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    statements: tuple[WikidataStatement, ...] = ()
    url: str | None = None

    def values_for(self, property_id: str) -> tuple[WikidataStatement, ...]:
        return tuple(s for s in self.statements if s.property_id == property_id)


@dataclass(frozen=True)
class ModuleProfile:
    name: str
    entity_types: tuple[str, ...]
    gate_properties: tuple[str, ...] = ()
    indicator_terms: tuple[str, ...] = ()
    relation_properties: dict[str, str] = field(default_factory=dict)
    kind: str = "intrinsic"
    property_fields: tuple[str, ...] = ()
    relation_fields: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpansionConfig:
    language: str = "en"
    max_candidates_per_seed: int = 5
    min_accept_score: float = 0.72
    min_review_score: float = 0.45
    modules: tuple[ModuleProfile, ...] = ()
    property_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Evidence:
    source: str
    detail: str
    weight: float


@dataclass(frozen=True)
class Change:
    action: str
    entity_type: str
    label: str
    wikidata_id: str
    confidence: float
    module: str | None = None
    parent: str | None = None
    field: str | None = None
    value: str | None = None
    evidence: tuple[Evidence, ...] = ()
    review_required: bool = False


@dataclass(frozen=True)
class RefinementReport:
    total_candidates: int
    classified_candidates: int
    unclassified_candidates: int
    module_free_candidates: int
    category_counts: dict[str, int]
    module_counts: dict[str, int]
    uncovered_categories: tuple[str, ...]
    uncovered_modules: tuple[str, ...]


@dataclass
class ChangeSet:
    changes: list[Change] = field(default_factory=list)
    report: RefinementReport | None = None

    def add(self, change: Change) -> None:
        key = (
            change.action,
            change.entity_type,
            change.label.lower(),
            change.wikidata_id,
            change.field,
            change.value,
        )
        existing = {
            (c.action, c.entity_type, c.label.lower(), c.wikidata_id, c.field, c.value)
            for c in self.changes
        }
        if key not in existing:
            self.changes.append(change)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"changes": [asdict(change) for change in self.changes]}
        if self.report is not None:
            data["refinement_report"] = asdict(self.report)
        return data
