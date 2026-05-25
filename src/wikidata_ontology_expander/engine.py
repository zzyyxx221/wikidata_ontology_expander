from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover - optional in offline/test environments
    class _RequestsStub:
        class RequestException(Exception):
            pass

    requests = _RequestsStub()

from .model_review import build_reviewer
from .models import (
    Change,
    ChangeSet,
    Evidence,
    ExpansionConfig,
    ModelReviewConfig,
    ModuleProfile,
    RefinementReport,
    SchemaDocument,
    SeedEntity,
    WikidataEntity,
)
from .schema_parser import load_schema_document
from .scoring import GatePolicy
from .wikidata import WikidataClient


PROPERTY_PID_LABELS = {
    "P1448": ("officialName", "name"),
    "P1813": ("shortName", "name"),
    "P856": ("officialWebsite", "url"),
    "P571": ("inception", "date"),
    "P577": ("publishDate", "date"),
    "P31": ("instanceOf", "entity"),
    "P279": ("subclassOf", "entity"),
    "P452": ("belongsToIndustry", "entity"),
    "P176": ("manufacturer", "entity"),
    "P186": ("rawMaterial", "entity"),
    "P527": ("component", "entity"),
    "P178": ("developer", "entity"),
    "P127": ("shareholder", "entity"),
    "P355": ("childOrganization", "entity"),
    "P131": ("locatedInAdministrativeEntity", "entity"),
}

INSTANCE_LEVEL_FIELDS = {"description", "alias"}
INSTANCE_LEVEL_RELATIONS = {"subclassOf"}
INSTANCE_LIKE_PARENTS = {
    "business",
    "company",
    "corporation",
    "municipality of china",
    "city",
    "human",
}


@dataclass
class ProposalBucket:
    action: str
    entity_type: str
    label: str
    domain: str | None
    module: str | None
    parent: str | None = None
    field: str | None = None
    value: str | None = None
    target_type: str | None = None
    confidence_sum: float = 0.0
    support_keys: set[str] = dataclass_field(default_factory=set)
    examples: list[str] = dataclass_field(default_factory=list)
    evidence: list[Evidence] = dataclass_field(default_factory=list)
    source_entity_ids: list[str] = dataclass_field(default_factory=list)

    def add_candidate(
        self,
        candidate: WikidataEntity,
        confidence: float,
        examples: list[str],
        evidence: tuple[Evidence, ...],
    ) -> None:
        self.support_keys.add(_candidate_key(candidate))
        self.confidence_sum += confidence
        if candidate.source_id:
            self.source_entity_ids.append(candidate.source_id)
        for item in examples:
            if item not in self.examples:
                self.examples.append(item)
        for item in evidence:
            if item not in self.evidence:
                self.evidence.append(item)

    @property
    def support(self) -> int:
        return len(self.support_keys)

    @property
    def confidence(self) -> float:
        if not self.support_keys:
            return 0.0
        return min(self.confidence_sum / len(self.support_keys), 0.99)

    @property
    def unique_source_entity_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.source_entity_ids))


class ExpansionEngine:
    def __init__(
        self,
        client: WikidataClient,
        config: ExpansionConfig,
        continue_on_error: bool = False,
    ):
        self.client = client
        self.config = config
        self.gate = GatePolicy(config.modules)
        self.continue_on_error = continue_on_error
        self.reviewer = build_reviewer(config.model_review)

    def expand(self, schema_path: Path, seeds: list[SeedEntity]) -> ChangeSet:
        schema_doc = load_schema_document(schema_path)
        candidates = self._collect_seed_candidates(seeds, schema_doc)
        return self._build_schema_changeset(schema_doc, candidates, seeds=seeds)

    def expand_corpus(self, schema_path: Path, candidates: list[WikidataEntity]) -> ChangeSet:
        schema_doc = load_schema_document(schema_path)
        return self._build_schema_changeset(schema_doc, candidates, seeds=None)

    def _collect_seed_candidates(self, seeds: list[SeedEntity], schema_doc: SchemaDocument) -> list[tuple[SeedEntity, WikidataEntity]]:
        properties = self._properties_to_fetch()
        pairs: list[tuple[SeedEntity, WikidataEntity]] = []
        for seed in seeds:
            seen_candidates: set[str] = set()
            for term in seed.search_terms:
                remaining = self.config.max_candidates_per_seed - len(seen_candidates)
                if remaining <= 0:
                    break
                try:
                    candidates = self.client.search(term, limit=remaining)
                except requests.RequestException as exc:
                    self._handle_request_error(f"search term '{term}'", exc)
                    continue
                for candidate in candidates:
                    candidate_key = _candidate_key(candidate)
                    if candidate_key in seen_candidates:
                        continue
                    seen_candidates.add(candidate_key)
                    if len(seen_candidates) > self.config.max_candidates_per_seed:
                        break
                    enriched = candidate
                    if candidate.source_id:
                        try:
                            enriched = self.client.get_entity(candidate.source_id, properties=properties)
                        except requests.RequestException as exc:
                            self._handle_request_error(f"entity '{candidate.source_id}'", exc)
                            continue
                    pairs.append((seed, enriched))
        return pairs

    def _build_schema_changeset(
        self,
        schema_doc: SchemaDocument,
        collected: list[tuple[SeedEntity, WikidataEntity]] | list[WikidataEntity],
        seeds: list[SeedEntity] | None,
    ) -> ChangeSet:
        changeset = ChangeSet()
        category_counts: Counter[str] = Counter()
        module_counts: Counter[str] = Counter()
        total_candidates = 0
        unclassified_candidates = 0
        module_free_candidates = 0
        schema_entity_labels = {entity.label.lower() for entity in schema_doc.entities.values() if entity.label}
        schema_entity_names = {name.lower() for name in schema_doc.entities}
        schema_known_terms = schema_entity_labels | schema_entity_names
        schema_fields_by_entity = _schema_fields_by_entity(schema_doc)
        schema_relation_fields_by_entity = _schema_relation_fields_by_entity(schema_doc)
        relation_modules_by_domain = _relation_modules_by_domain(schema_doc)
        relation_lookup = _build_relation_lookup(self.config.modules)

        concept_buckets: dict[tuple, ProposalBucket] = {}
        property_buckets: dict[tuple, ProposalBucket] = {}
        relation_buckets: dict[tuple, ProposalBucket] = {}
        gate_buckets: dict[tuple, ProposalBucket] = {}
        module_buckets: dict[tuple, ProposalBucket] = {}

        if seeds is None:
            iterable = [(SeedEntity(name="", entity_type=""), candidate) for candidate in collected]
            include_retrieval = False
        else:
            iterable = collected
            include_retrieval = True

        for seed, candidate in iterable:
            total_candidates += 1
            scored = self.gate.classify(
                seed,
                candidate,
                schema_modules=schema_doc.modules,
                relation_lookup=relation_lookup,
                property_map=self.config.property_map,
                include_retrieval=include_retrieval,
            )
            if scored.category:
                category_counts[scored.category] += 1
            else:
                unclassified_candidates += 1
            if scored.module:
                module_counts[scored.module] += 1
            else:
                module_free_candidates += 1
            if not scored.category:
                self._collect_category_gate_proposals(
                    candidate=candidate,
                    schema_doc=schema_doc,
                    gate_buckets=gate_buckets,
                )
                continue
            if scored.score < self.config.min_review_score:
                continue

            domain = scored.category
            entity_type = seed.entity_type or _entity_type_for_candidate(scored.category, candidate, schema_doc, self.config)
            if not scored.module:
                self._collect_module_proposals(
                    candidate=candidate,
                    domain=domain,
                    entity_type=entity_type,
                    scored=scored,
                    schema_fields_by_entity=schema_fields_by_entity,
                    schema_relation_fields_by_entity=schema_relation_fields_by_entity,
                    module_buckets=module_buckets,
                )
            concept_key = ("add_concept", domain, entity_type, candidate.label.lower())
            if _should_propose_concept(candidate, seed, schema_known_terms, allow_without_seed=seeds is None):
                bucket = concept_buckets.setdefault(
                    concept_key,
                    ProposalBucket(
                        action="add_concept",
                        entity_type=entity_type,
                        label=candidate.label,
                        domain=domain,
                        module=scored.module,
                        parent=_best_parent_label(candidate),
                    ),
                )
                bucket.add_candidate(
                    candidate,
                    scored.score,
                    examples=[_candidate_example(candidate)],
                    evidence=scored.evidence,
                )

            for statement in candidate.statements:
                if statement.property_id in {"P31", "P279"}:
                    continue
                suggested_field, target_type = _infer_schema_slot(statement, domain, self.config)
                if not suggested_field:
                    continue
                if suggested_field in INSTANCE_LEVEL_FIELDS:
                    continue

                if (
                    suggested_field not in schema_fields_by_entity.get(entity_type, set())
                    and suggested_field not in schema_relation_fields_by_entity.get(entity_type, set())
                ):
                    action = "add_relation_type" if target_type == "entity" else "add_property_type"
                    bucket_map = relation_buckets if action == "add_relation_type" else property_buckets
                    key = (action, domain, entity_type, suggested_field)
                    bucket = bucket_map.setdefault(
                        key,
                        ProposalBucket(
                            action=action,
                            entity_type=entity_type,
                            label=entity_type,
                            domain=domain,
                            module=_resolve_schema_module_name(
                                domain=domain,
                                field_name=suggested_field,
                                action=action,
                                scored_module=scored.module,
                                relation_modules_by_domain=relation_modules_by_domain,
                            ),
                            field=suggested_field,
                            target_type=_normalize_target_type(target_type, statement.value_label),
                            value=statement.property_label,
                        ),
                    )
                    example = f"{candidate.label} -> {suggested_field} -> {statement.value_label}"
                    evidence = scored.evidence + (
                        Evidence(
                            source="statement",
                            detail=f"{statement.property_id} / {statement.property_label}",
                            weight=0.18,
                        ),
                    )
                    bucket.add_candidate(candidate, scored.score, [example], evidence)

        all_buckets = (
            list(gate_buckets.values())
            + list(module_buckets.values())
            + list(concept_buckets.values())
            + list(property_buckets.values())
            + list(relation_buckets.values())
        )
        for bucket in all_buckets:
            if bucket.support < self.config.proposal_min_support:
                continue
            proposal = self._proposal_from_bucket(bucket)
            reviewed = self.reviewer.review(proposal)
            if not reviewed.accepted:
                continue
            confidence = round(max(proposal.confidence, reviewed.confidence), 4)
            review_required = confidence < self.config.min_accept_score
            changeset.add(
                Change(
                    action=proposal.action,
                    entity_type=proposal.entity_type,
                    label=reviewed.normalized_label or proposal.label,
                    confidence=confidence,
                    domain=proposal.domain,
                    module=proposal.module,
                    parent=proposal.parent,
                    field=proposal.field,
                    value=reviewed.normalized_value or proposal.value,
                    target_type=reviewed.normalized_target_type or proposal.target_type,
                    support=proposal.support,
                    examples=proposal.examples,
                    rationale=reviewed.rationale,
                    evidence=proposal.evidence,
                    source_entity_ids=proposal.source_entity_ids,
                    review_required=review_required,
                )
            )

        changeset.report = _build_refinement_report(
            schema_doc.modules,
            category_counts,
            module_counts,
            total_candidates,
            unclassified_candidates,
            module_free_candidates,
        )
        return changeset

    def _collect_category_gate_proposals(
        self,
        candidate: WikidataEntity,
        schema_doc: SchemaDocument,
        gate_buckets: dict[tuple, ProposalBucket],
    ) -> None:
        for statement in candidate.statements:
            if statement.property_id not in {"P31", "P279"} or not statement.value_label:
                continue
            domain = _suggest_category_for_gate(statement.value_label, candidate, self.config)
            if not domain:
                continue
            entity_type = _entity_type_for_category(domain, schema_doc, self.config)
            key = ("add_category_gate", domain, entity_type, statement.property_id, statement.value_label.lower())
            bucket = gate_buckets.setdefault(
                key,
                ProposalBucket(
                    action="add_category_gate",
                    entity_type=entity_type,
                    label=statement.value_label,
                    domain=domain,
                    module=None,
                    field=_gate_field_name(statement.property_id),
                    value=statement.property_label,
                    target_type="gate_type",
                ),
            )
            bucket.add_candidate(
                candidate,
                0.55,
                [f"{candidate.label} -> {statement.property_label} -> {statement.value_label}"],
                (
                    Evidence("unclassified", f"candidate could not be routed into any existing category", 0.2),
                    Evidence("gate_statement", f"{statement.property_id} / {statement.property_label}", 0.35),
                ),
            )

    def _collect_module_proposals(
        self,
        candidate: WikidataEntity,
        domain: str,
        entity_type: str,
        scored,
        schema_fields_by_entity: dict[str, set[str]],
        schema_relation_fields_by_entity: dict[str, set[str]],
        module_buckets: dict[tuple, ProposalBucket],
    ) -> None:
        for statement in candidate.statements:
            if statement.property_id in {"P31", "P279"}:
                continue
            suggested_field, target_type = _infer_schema_slot(statement, domain, self.config)
            if not suggested_field or suggested_field in INSTANCE_LEVEL_FIELDS:
                continue
            if (
                suggested_field in schema_fields_by_entity.get(entity_type, set())
                or suggested_field in schema_relation_fields_by_entity.get(entity_type, set())
            ):
                continue
            kind = "relational" if target_type == "entity" else "intrinsic"
            module_name = _suggest_module_name(suggested_field, kind)
            key = ("add_module", domain, entity_type, module_name)
            bucket = module_buckets.setdefault(
                key,
                ProposalBucket(
                    action="add_module",
                    entity_type=entity_type,
                    label=module_name,
                    domain=domain,
                    module=module_name,
                    field=suggested_field,
                    value=statement.property_label,
                    target_type=kind,
                ),
            )
            bucket.add_candidate(
                candidate,
                max(scored.category_score, 0.45),
                [f"{candidate.label} -> {module_name} -> {suggested_field}"],
                scored.evidence
                + (
                    Evidence("module_gap", "candidate matched a category but no existing module", 0.18),
                    Evidence("statement", f"{statement.property_id} / {statement.property_label}", 0.18),
                ),
            )

    def _proposal_from_bucket(self, bucket: ProposalBucket) -> Change:
        return Change(
            action=bucket.action,
            entity_type=bucket.entity_type,
            label=bucket.label,
            confidence=round(bucket.confidence, 4),
            domain=bucket.domain,
            module=bucket.module,
            parent=bucket.parent,
            field=bucket.field,
            value=bucket.value,
            target_type=bucket.target_type,
            support=bucket.support,
            examples=tuple(bucket.examples[:6]),
            evidence=tuple(bucket.evidence),
            source_entity_ids=bucket.unique_source_entity_ids,
            review_required=bucket.confidence < self.config.min_accept_score,
        )

    def _handle_request_error(self, context: str, exc: requests.RequestException) -> None:
        if not self.continue_on_error:
            raise exc
        print(f"[warn] skipped Wikidata {context}: {exc}")

    def _properties_to_fetch(self) -> tuple[str, ...]:
        pids = set(self.config.property_map.values())
        pids.update(PROPERTY_PID_LABELS)
        for module in self.config.modules:
            pids.update(module.gate_properties)
            pids.update(module.relation_properties.values())
        return tuple(sorted(pids))


def load_seeds(path: Path) -> list[SeedEntity]:
    data = json.loads(path.read_text(encoding="utf-8"))
    seeds = data.get("seeds", data)
    return [
        SeedEntity(
            name=item["name"],
            entity_type=item["entity_type"],
            external_id=item.get("external_id") or item.get("qid"),
            aliases=tuple(item.get("aliases", [])),
            module=item.get("module"),
            parent=item.get("parent"),
        )
        for item in seeds
    ]


def load_config(path: Path, schema_path: Path | None = None) -> ExpansionConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema_modules: dict[str, tuple[str, ...]] = {}
    if schema_path is not None:
        schema_doc = load_schema_document(schema_path)
        schema_modules = {domain.key: domain.entity_types for domain in schema_doc.domains}
    modules = tuple(
        ModuleProfile(
            name=item["name"],
            entity_types=_merge_entity_types(
                tuple(item.get("entity_types", [])),
                schema_modules.get(item["name"], ()),
            ),
            gate_properties=tuple(item.get("gate_properties", [])),
            category_gate_labels=tuple(item.get("category_gate_labels", [])),
            indicator_terms=tuple(item.get("indicator_terms", [])),
            relation_properties=dict(item.get("relation_properties", {})),
        )
        for item in data.get("modules", [])
    )
    model_review_data = data.get("model_review")
    model_review = None
    if model_review_data is not None:
        model_review = ModelReviewConfig(
            enabled=bool(model_review_data.get("enabled", False)),
            provider=model_review_data.get("provider", "openai"),
            model=model_review_data.get("model", "gpt-5-mini"),
            api_base=model_review_data.get("api_base", "https://api.openai.com/v1"),
            api_key_env=model_review_data.get("api_key_env", "OPENAI_API_KEY"),
            temperature=float(model_review_data.get("temperature", 0.0)),
            max_output_tokens=int(model_review_data.get("max_output_tokens", 600)),
        )
    return ExpansionConfig(
        language=data.get("language", "en"),
        max_candidates_per_seed=int(data.get("max_candidates_per_seed", 5)),
        min_accept_score=float(data.get("min_accept_score", 0.72)),
        min_review_score=float(data.get("min_review_score", 0.45)),
        proposal_min_support=int(data.get("proposal_min_support", 1)),
        modules=modules,
        property_map=dict(data.get("property_map", {})),
        model_review=model_review,
    )


def _merge_entity_types(base: tuple[str, ...], derived: tuple[str, ...]) -> tuple[str, ...]:
    if not derived:
        return base
    merged: list[str] = []
    for item in (*base, *derived):
        if item not in merged:
            merged.append(item)
    return tuple(merged)


def _build_relation_lookup(modules: tuple[ModuleProfile, ...]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for module in modules:
        lookup.update(module.relation_properties)
    return lookup


def _entity_type_for_category(category: str | None, schema_doc: SchemaDocument, config: ExpansionConfig) -> str:
    if category:
        for domain in schema_doc.domains:
            if domain.key == category and domain.entity_types:
                return domain.entity_types[0]
        for module in config.modules:
            if module.name == category and module.entity_types:
                return module.entity_types[0]
    return "Thing"


def _entity_type_for_candidate(
    category: str | None,
    candidate: WikidataEntity,
    schema_doc: SchemaDocument,
    config: ExpansionConfig,
) -> str:
    inferred = _infer_entity_type_from_candidate(category, candidate)
    if inferred and inferred in schema_doc.entities:
        return inferred
    return _entity_type_for_category(category, schema_doc, config)


def _infer_entity_type_from_candidate(category: str | None, candidate: WikidataEntity) -> str | None:
    haystack = " ".join(
        (
            candidate.label,
            candidate.description,
            " ".join(candidate.aliases),
            " ".join(statement.value_label for statement in candidate.statements),
        )
    ).lower()
    if category == "industry":
        if "economic sector" in haystack or "sector" in haystack:
            return "EconomicSector"
        if "industry group" in haystack or "group" in haystack:
            return "IndustryGroup"
        return "Industry"
    if category == "product":
        if "model" in haystack or any(token in candidate.label for token in ("H100", "A100")):
            return "ProductModel"
        if "term" in haystack:
            return "ProductTerm"
        return "Product"
    if category == "technology":
        if "patent" in haystack:
            return "Patent"
        return "Technology"
    if category == "organization":
        if "research institute" in haystack or "laboratory" in haystack:
            return "ResearchInstitute"
        if "university" in haystack:
            return "University"
        return "Organization"
    if category == "event":
        if "research institute" in haystack or "research event" in haystack:
            return "ResearchInstituteEvent"
        return "EnterpriseEvent"
    if category == "document":
        if "chunk" in haystack or "fragment" in haystack:
            return "Chunk"
        if "report" in haystack or "publication" in haystack or "document" in haystack:
            return "Document"
        if "source" in haystack or "dataset" in haystack:
            return "DataSource"
        return "Document"
    if category == "enterprise":
        return "Enterprise"
    if category == "person":
        return "Person"
    if category == "region":
        return "Region"
    if category == "policy":
        return "Policy"
    if category == "index":
        return "Index"
    return None


def _schema_fields_by_entity(schema_doc: SchemaDocument) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for entity in schema_doc.entities.values():
        mapping[entity.name].update(field.name for field in entity.fields if field.section == "property")
    return mapping


def _schema_relation_fields_by_entity(schema_doc: SchemaDocument) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for entity in schema_doc.entities.values():
        mapping[entity.name].update(field.name for field in entity.fields if field.section == "relation")
    return mapping


def _relation_modules_by_domain(schema_doc: SchemaDocument) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = defaultdict(dict)
    for module in schema_doc.modules:
        if module.kind not in ("relational", "mixed"):
            continue
        for field_name in module.relation_fields:
            mapping[module.domain][field_name] = module.name
    return mapping


def _infer_schema_slot(statement, domain: str | None = None, config: ExpansionConfig | None = None) -> tuple[str | None, str | None]:
    configured_field = _configured_field_for_property(statement.property_id, domain, config)
    if configured_field:
        return configured_field, "entity" if statement.value_id else _guess_literal_target(statement.value_label)
    if statement.property_id in PROPERTY_PID_LABELS:
        return PROPERTY_PID_LABELS[statement.property_id]
    if not statement.property_label:
        return None, None
    normalized = _camel_case(statement.property_label)
    if not normalized:
        return None, None
    target_type = "entity" if statement.value_id else _guess_literal_target(statement.value_label)
    return normalized, target_type


def _configured_field_for_property(
    property_id: str,
    domain: str | None,
    config: ExpansionConfig | None,
) -> str | None:
    if not config:
        return None
    for module in (module for module in config.modules if module.name == domain):
        for field_name, mapped_property_id in module.relation_properties.items():
            if mapped_property_id == property_id:
                return field_name
    for field_name, mapped_property_id in config.property_map.items():
        if mapped_property_id == property_id:
            return field_name
    return None


def _resolve_schema_module_name(
    domain: str,
    field_name: str,
    action: str,
    scored_module: str | None,
    relation_modules_by_domain: dict[str, dict[str, str]],
) -> str | None:
    if action == "add_relation_type":
        return relation_modules_by_domain.get(domain, {}).get(field_name, domain)
    return scored_module


def _normalize_target_type(target_type: str | None, value_label: str) -> str | None:
    if target_type != "entity":
        return target_type
    text = value_label.lower()
    if any(token in text for token in ("panasonic", "tesla", "tsmc")):
        return "Enterprise"
    if any(token in text for token in ("asml", "toyota")):
        return "Enterprise"
    if any(token in text for token in ("industry", "sector")):
        return "Industry"
    if any(token in text for token in ("company", "business", "manufacturer")):
        return "Enterprise"
    if any(token in text for token in ("material", "component", "battery", "vehicle", "product")):
        return "Product"
    if any(token in text for token in ("technology", "process", "engineering", "lithography")):
        return "Technology"
    if any(token in text for token in ("document", "patent")):
        return "Document"
    if any(token in text for token in ("municipality", "city", "country", "region")):
        return "Region"
    return "Thing"


def _guess_literal_target(value_label: str) -> str:
    if value_label.startswith("http://") or value_label.startswith("https://"):
        return "url"
    if value_label.startswith("+") and "T" in value_label:
        return "date"
    return "text"


def _camel_case(text: str) -> str:
    parts = [segment for segment in "".join(ch if ch.isalnum() else " " for ch in text).split() if segment]
    if not parts:
        return ""
    return parts[0].lower() + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _candidate_key(candidate: WikidataEntity) -> str:
    return candidate.identity_key


def _candidate_example(candidate: WikidataEntity) -> str:
    if candidate.source_id:
        return f"{candidate.label} ({candidate.source_id})"
    return candidate.label


def _text_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in "".join(ch if ch.isalnum() else " " for ch in text).split()
        if token
    }


def _suggest_category_for_gate(text: str, candidate: WikidataEntity, config: ExpansionConfig) -> str | None:
    haystack = f"{text} {candidate.label} {candidate.description}"
    tokens = _text_tokens(haystack)
    normalized_target = _normalize_target_type("entity", text) or "Thing"
    best_name: str | None = None
    best_score = 0
    for module in config.modules:
        score = 0
        if normalized_target in module.entity_types:
            score += 4
        if module.name.lower() in haystack.lower():
            score += 2
        score += sum(1 for term in module.indicator_terms if term.lower() in haystack.lower())
        score += sum(1 for entity_type in module.entity_types if entity_type.lower() in haystack.lower())
        module_name_tokens = _text_tokens(module.name)
        if module_name_tokens & tokens:
            score += len(module_name_tokens & tokens)
        if score > best_score:
            best_name = module.name
            best_score = score
    return best_name if best_score > 0 else None


def _gate_field_name(property_id: str) -> str:
    if property_id == "P31":
        return "instanceOf"
    if property_id == "P279":
        return "subclassOf"
    return property_id


def _suggest_module_name(field_name: str, kind: str) -> str:
    suffix = "relations" if kind == "relational" else "properties"
    return f"{_snake_case(field_name)}_{suffix}"


def _snake_case(text: str) -> str:
    chars: list[str] = []
    for index, ch in enumerate(text):
        if ch.isupper() and index > 0 and (text[index - 1].islower() or (index + 1 < len(text) and text[index + 1].islower())):
            chars.append("_")
        chars.append(ch.lower())
    return "".join(chars)


def _best_parent_label(candidate: WikidataEntity) -> str | None:
    for statement in candidate.statements:
        if statement.property_id == "P279":
            return statement.value_label
    for statement in candidate.statements:
        if statement.property_id == "P31":
            return statement.value_label
    return None


def _should_propose_concept(
    candidate: WikidataEntity,
    seed: SeedEntity,
    schema_known_terms: set[str],
    allow_without_seed: bool,
) -> bool:
    if not allow_without_seed and not seed.search_terms:
        return False
    candidate_terms = {candidate.label.lower(), *(alias.lower() for alias in candidate.aliases)}
    seed_terms = {term.lower() for term in seed.search_terms if term}
    if candidate_terms & seed_terms:
        return False
    if candidate.label.lower() in schema_known_terms:
        return False

    parent = (_best_parent_label(candidate) or "").lower()
    if parent in INSTANCE_LIKE_PARENTS:
        return False

    label = candidate.label
    description = candidate.description.lower()
    if any(token in label for token in (",", "Inc.", "Company", "Municipality")):
        return False
    if any(
        phrase in description
        for phrase in (
            "american ",
            "taiwanese ",
            "municipality",
            "company",
            "corporation",
        )
    ):
        return False

    if seed.parent:
        parent_terms = {seed.parent.lower(), seed.name.lower(), *(alias.lower() for alias in seed.aliases)}
        if parent in parent_terms:
            return False
        if parent and parent not in parent_terms and all(term not in parent for term in parent_terms):
            if candidate.label.lower() not in parent_terms:
                return False
    elif not allow_without_seed:
        return False

    return True


def _build_refinement_report(
    schema_modules: tuple,
    category_counts: Counter[str],
    module_counts: Counter[str],
    total_candidates: int,
    unclassified_candidates: int,
    module_free_candidates: int,
) -> RefinementReport:
    category_names = tuple(dict.fromkeys(module.domain for module in schema_modules if module.domain))
    module_names = tuple(dict.fromkeys(module.name for module in schema_modules))
    uncovered_categories = tuple(name for name in category_names if category_counts.get(name, 0) == 0)
    uncovered_modules = tuple(name for name in module_names if module_counts.get(name, 0) == 0)
    classified_candidates = total_candidates - unclassified_candidates
    return RefinementReport(
        total_candidates=total_candidates,
        classified_candidates=classified_candidates,
        unclassified_candidates=unclassified_candidates,
        module_free_candidates=module_free_candidates,
        category_counts=dict(category_counts),
        module_counts=dict(module_counts),
        uncovered_categories=uncovered_categories,
        uncovered_modules=uncovered_modules,
    )
