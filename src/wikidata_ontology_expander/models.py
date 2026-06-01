from __future__ import annotations

from dataclasses import asdict, dataclass, field
from dataclasses import field as dataclass_field
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
    external_id: str | None = None
    aliases: tuple[str, ...] = ()
    module: str | None = None
    parent: str | None = None

    @property
    def search_terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.name, *self.aliases)))

    @property
    def qid(self) -> str | None:
        return self.external_id


@dataclass(frozen=True)
class WikidataStatement:
    property_id: str
    property_label: str
    value_id: str | None
    value_label: str
    raw_value: Any = None


@dataclass(frozen=True)
class WikidataEntity:
    label: str
    source_id: str | None = None
    description: str = ""
    aliases: tuple[str, ...] = ()
    statements: tuple[WikidataStatement, ...] = ()
    url: str | None = None

    def values_for(self, property_id: str) -> tuple[WikidataStatement, ...]:
        return tuple(s for s in self.statements if s.property_id == property_id)

    @property
    def qid(self) -> str | None:
        return self.source_id

    @property
    def identity_key(self) -> str:
        if self.source_id:
            return f"id:{self.source_id}"
        aliases = ",".join(alias.strip().lower() for alias in self.aliases if alias.strip())
        description = self.description.strip().lower()
        return f"label:{self.label.strip().lower()}|aliases:{aliases}|description:{description}"


@dataclass(frozen=True)
class EntityTypeRule:
    entity_type: str
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleProfile:
    name: str
    entity_types: tuple[str, ...]
    gate_properties: tuple[str, ...] = ()
    category_gate_labels: tuple[str, ...] = ()
    indicator_terms: tuple[str, ...] = ()
    relation_properties: dict[str, str] = field(default_factory=dict)
    entity_type_rules: tuple[EntityTypeRule, ...] = ()
    kind: str = "intrinsic"
    property_fields: tuple[str, ...] = ()
    relation_fields: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelReviewConfig:
    enabled: bool = False
    provider: str = "openai"
    model: str = "gpt-5-mini"
    api_base: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.0
    max_output_tokens: int = 600


@dataclass(frozen=True)
class ExpansionConfig:
    language: str = "en"
    freeze_top_level_schema: bool = False
    allowed_schema_actions: tuple[str, ...] = ()
    restricted_schema_actions: tuple[str, ...] = ()
    require_taxonomy_context: bool = False
    taxonomy_context_domains: tuple[str, ...] = ("industry", "product")
    prefer_leaf_taxonomy_evidence: bool = False
    max_candidates_per_seed: int = 5
    min_accept_score: float = 0.72
    min_review_score: float = 0.45
    proposal_min_support: int = 1
    modules: tuple[ModuleProfile, ...] = ()
    property_map: dict[str, str] = field(default_factory=dict)
    model_review: ModelReviewConfig | None = None


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
    confidence: float
    domain: str | None = None
    module: str | None = None
    parent: str | None = None
    field: str | None = None
    value: str | None = None
    target_type: str | None = None
    support: int = 0
    examples: tuple[str, ...] = ()
    rationale: str | None = None
    evidence: tuple[Evidence, ...] = ()
    source_entity_ids: tuple[str, ...] = ()
    review_required: bool = False
    model_review: dict[str, Any] = dataclass_field(default_factory=dict)
    classification: dict[str, Any] = dataclass_field(default_factory=dict)


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

    def add(self, change: Change) -> bool:
        key = (
            change.action,
            change.entity_type,
            change.label.lower(),
            change.domain,
            change.module,
            change.field,
            change.value,
            change.target_type,
        )
        existing = {
            (
                c.action,
                c.entity_type,
                c.label.lower(),
                c.domain,
                c.module,
                c.field,
                c.value,
                c.target_type,
            )
            for c in self.changes
        }
        if key not in existing:
            self.changes.append(change)
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"changes": [asdict(change) for change in self.changes]}
        if self.report is not None:
            data["refinement_report"] = asdict(self.report)
        return data
