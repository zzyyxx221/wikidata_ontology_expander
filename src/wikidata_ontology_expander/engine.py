from __future__ import annotations

import json
from pathlib import Path
from collections import Counter

try:
    import requests
except ImportError:  # pragma: no cover - optional in offline/test environments
    class _RequestsStub:
        class RequestException(Exception):
            pass

    requests = _RequestsStub()

from .models import (
    Change,
    ChangeSet,
    ExpansionConfig,
    ModuleProfile,
    SeedEntity,
    RefinementReport,
    WikidataEntity,
)
from .schema_parser import load_schema_document
from .scoring import GatePolicy
from .wikidata import WikidataClient


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

    def expand(self, schema_path: Path, seeds: list[SeedEntity]) -> ChangeSet:
        schema_doc = load_schema_document(schema_path)
        schema = schema_doc.entities
        changeset = ChangeSet()
        known_labels = {seed.name.lower() for seed in seeds}
        known_labels.update(entity.label.lower() for entity in schema.values() if entity.label)
        category_by_entity_type = {
            entity_type: domain.key for domain in schema_doc.domains for entity_type in domain.entity_types
        }
        modules_by_domain = _group_modules_by_domain(schema_doc.modules)
        relation_lookup = _build_relation_lookup(self.config.modules)
        category_counts: Counter[str] = Counter()
        module_counts: Counter[str] = Counter()
        total_candidates = 0
        unclassified_candidates = 0
        module_free_candidates = 0

        properties = self._properties_to_fetch()
        for seed in seeds:
            seed_domain = category_by_entity_type.get(seed.entity_type) or _infer_category_name(
                seed.entity_type, self.config.modules, seed.module
            )
            seen_qids: set[str] = set()
            for term in seed.search_terms:
                remaining = self.config.max_candidates_per_seed - len(seen_qids)
                if remaining <= 0:
                    break
                try:
                    candidates = self.client.search(term, limit=remaining)
                except requests.RequestException as exc:
                    self._handle_request_error(f"search term '{term}'", exc)
                    continue
                for candidate in candidates:
                    if candidate.qid in seen_qids:
                        continue
                    seen_qids.add(candidate.qid)
                    if len(seen_qids) > self.config.max_candidates_per_seed:
                        break
                    try:
                        enriched = self.client.get_entity(candidate.qid, properties=properties)
                    except requests.RequestException as exc:
                        self._handle_request_error(f"entity '{candidate.qid}'", exc)
                        continue
                    total_candidates += 1
                    scored = self.gate.classify(
                        seed,
                        enriched,
                        schema_modules=schema_doc.modules,
                        relation_lookup=relation_lookup,
                        property_map=self.config.property_map,
                    )
                    if scored.category:
                        category_counts[scored.category] += 1
                    else:
                        unclassified_candidates += 1
                    if scored.module:
                        module_counts[scored.module] += 1
                    else:
                        module_free_candidates += 1
                    if scored.score < self.config.min_review_score:
                        continue
                    if not scored.category and not scored.module:
                        continue

                    active_domain = scored.category or seed_domain
                    review_required = scored.score < self.config.min_accept_score
                    action = "review_required" if review_required else "add_entity"
                    if enriched.label.lower() in known_labels:
                        action = "enrich_existing"

                    changeset.add(
                        Change(
                            action=action,
                            entity_type=seed.entity_type,
                            label=enriched.label,
                            wikidata_id=enriched.qid,
                            confidence=round(scored.score, 4),
                            module=scored.module,
                            parent=seed.parent,
                            evidence=scored.evidence,
                            review_required=review_required,
                        )
                    )
                    self._add_property_enrichment(
                        changeset,
                        seed,
                        enriched,
                        scored.score,
                        review_required,
                        active_domain,
                        modules_by_domain,
                    )
                    self._add_relation_expansion(
                        changeset,
                        seed,
                        enriched,
                        scored.score,
                        review_required,
                        active_domain,
                        modules_by_domain,
                        relation_lookup,
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

    def expand_corpus(self, schema_path: Path, candidates: list[WikidataEntity]) -> ChangeSet:
        schema_doc = load_schema_document(schema_path)
        schema = schema_doc.entities
        changeset = ChangeSet()
        known_labels = {entity.label.lower() for entity in schema.values() if entity.label}
        modules_by_domain = _group_modules_by_domain(schema_doc.modules)
        relation_lookup = _build_relation_lookup(self.config.modules)
        category_counts: Counter[str] = Counter()
        module_counts: Counter[str] = Counter()
        total_candidates = 0
        unclassified_candidates = 0
        module_free_candidates = 0

        empty_seed = SeedEntity(name="", entity_type="")
        for candidate in candidates:
            total_candidates += 1
            scored = self.gate.classify(
                empty_seed,
                candidate,
                schema_modules=schema_doc.modules,
                relation_lookup=relation_lookup,
                property_map=self.config.property_map,
                include_retrieval=False,
            )
            if scored.category:
                category_counts[scored.category] += 1
            else:
                unclassified_candidates += 1
            if scored.module:
                module_counts[scored.module] += 1
            else:
                module_free_candidates += 1
            if scored.score < self.config.min_review_score:
                continue
            if not scored.category and not scored.module:
                continue

            active_domain = scored.category
            entity_type = _entity_type_for_category(scored.category, schema_doc, self.config)
            seed = SeedEntity(
                name=candidate.label,
                entity_type=entity_type,
                aliases=candidate.aliases,
                module=scored.module or scored.category,
            )
            review_required = scored.score < self.config.min_accept_score
            action = "review_required" if review_required else "add_entity"
            if candidate.label.lower() in known_labels:
                action = "enrich_existing"

            changeset.add(
                Change(
                    action=action,
                    entity_type=entity_type,
                    label=candidate.label,
                    wikidata_id=candidate.qid,
                    confidence=round(scored.score, 4),
                    module=scored.module,
                    evidence=scored.evidence,
                    review_required=review_required,
                )
            )
            self._add_property_enrichment(
                changeset,
                seed,
                candidate,
                scored.score,
                review_required,
                active_domain,
                modules_by_domain,
            )
            self._add_relation_expansion(
                changeset,
                seed,
                candidate,
                scored.score,
                review_required,
                active_domain,
                modules_by_domain,
                relation_lookup,
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

    def _handle_request_error(self, context: str, exc: requests.RequestException) -> None:
        if not self.continue_on_error:
            raise exc
        print(f"[warn] skipped Wikidata {context}: {exc}")

    def _properties_to_fetch(self) -> tuple[str, ...]:
        pids = set(self.config.property_map.values())
        for module in self.config.modules:
            pids.update(module.gate_properties)
            pids.update(module.relation_properties.values())
        return tuple(sorted(pids))

    def _add_property_enrichment(
        self,
        changeset: ChangeSet,
        seed: SeedEntity,
        entity: WikidataEntity,
        base_score: float,
        review_required: bool,
        seed_domain: str | None,
        modules_by_domain: dict[str, tuple],
    ) -> None:
        intrinsic_modules = [module for module in _modules_for_domain(modules_by_domain, seed_domain) if getattr(module, "kind", "intrinsic") != "relational"]
        generic_module = next((module for module in intrinsic_modules if module.name == "common_properties"), intrinsic_modules[0] if intrinsic_modules else None)
        if generic_module is not None:
            if entity.description:
                changeset.add(
                    Change(
                        action="enrich_property",
                        entity_type=seed.entity_type,
                        label=entity.label,
                        wikidata_id=entity.qid,
                        confidence=round(min(base_score, 0.95), 4),
                        module=generic_module.name,
                        field="description",
                        value=entity.description,
                        review_required=review_required,
                    )
                )
            if entity.aliases:
                changeset.add(
                    Change(
                        action="enrich_property",
                        entity_type=seed.entity_type,
                        label=entity.label,
                        wikidata_id=entity.qid,
                        confidence=round(min(base_score, 0.95), 4),
                        module=generic_module.name,
                        field="alias",
                        value="; ".join(entity.aliases[:8]),
                        review_required=review_required,
                    )
                )
        for module in intrinsic_modules:
            for field_name, pid in self.config.property_map.items():
                if field_name not in getattr(module, "property_fields", ()):
                    continue
                values = entity.values_for(pid)
                if not values:
                    continue
                changeset.add(
                    Change(
                        action="enrich_property",
                        entity_type=seed.entity_type,
                        label=entity.label,
                        wikidata_id=entity.qid,
                        confidence=round(min(base_score, 0.9), 4),
                        module=module.name,
                        field=field_name,
                        value="; ".join(v.value_label for v in values[:8]),
                        review_required=review_required,
                    )
                )

    def _add_relation_expansion(
        self,
        changeset: ChangeSet,
        seed: SeedEntity,
        entity: WikidataEntity,
        base_score: float,
        review_required: bool,
        seed_domain: str | None,
        modules_by_domain: dict[str, tuple],
        relation_lookup: dict[str, str],
    ) -> None:
        for module in _modules_for_domain(modules_by_domain, seed_domain):
            if getattr(module, "kind", "intrinsic") == "intrinsic":
                continue
            for relation_name in getattr(module, "relation_fields", ()):
                pid = relation_lookup.get(relation_name)
                if pid is None:
                    continue
                values = entity.values_for(pid)
                for statement in values[:10]:
                    if not statement.value_id:
                        continue
                    changeset.add(
                        Change(
                            action="add_relation",
                            entity_type=seed.entity_type,
                            label=entity.label,
                            wikidata_id=entity.qid,
                            confidence=round(min(base_score * 0.9, 0.85), 4),
                            module=module.name,
                            field=relation_name,
                            value=f"{statement.value_label} ({statement.value_id})",
                            review_required=True if review_required else base_score < 0.82,
                        )
                    )


def load_seeds(path: Path) -> list[SeedEntity]:
    data = json.loads(path.read_text(encoding="utf-8"))
    seeds = data.get("seeds", data)
    return [
        SeedEntity(
            name=item["name"],
            entity_type=item["entity_type"],
            qid=item.get("qid"),
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
            indicator_terms=tuple(item.get("indicator_terms", [])),
            relation_properties=dict(item.get("relation_properties", {})),
        )
        for item in data.get("modules", [])
    )
    return ExpansionConfig(
        language=data.get("language", "en"),
        max_candidates_per_seed=int(data.get("max_candidates_per_seed", 5)),
        min_accept_score=float(data.get("min_accept_score", 0.72)),
        min_review_score=float(data.get("min_review_score", 0.45)),
        modules=modules,
        property_map=dict(data.get("property_map", {})),
    )


def _merge_entity_types(base: tuple[str, ...], derived: tuple[str, ...]) -> tuple[str, ...]:
    if not derived:
        return base
    merged: list[str] = []
    for item in (*base, *derived):
        if item not in merged:
            merged.append(item)
    return tuple(merged)


def _group_modules_by_domain(modules: tuple) -> dict[str, tuple]:
    grouped: dict[str, list] = {}
    for module in modules:
        grouped.setdefault(module.domain, []).append(module)
    return {domain: tuple(items) for domain, items in grouped.items()}


def _build_relation_lookup(modules: tuple[ModuleProfile, ...]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for module in modules:
        lookup.update(module.relation_properties)
    return lookup


def _infer_category_name(entity_type: str, modules: tuple[ModuleProfile, ...], fallback: str | None = None) -> str | None:
    for module in modules:
        if entity_type in module.entity_types:
            return module.name
    return fallback


def _entity_type_for_category(category: str | None, schema_doc, config: ExpansionConfig) -> str:
    if category:
        for domain in schema_doc.domains:
            if domain.key == category and domain.entity_types:
                return domain.entity_types[0]
        for module in config.modules:
            if module.name == category and module.entity_types:
                return module.entity_types[0]
    return "Thing"


def _modules_for_domain(modules_by_domain: dict[str, tuple], seed_domain: str | None) -> tuple:
    if seed_domain and seed_domain in modules_by_domain:
        return modules_by_domain[seed_domain]
    if modules_by_domain:
        all_modules: list = []
        for modules in modules_by_domain.values():
            all_modules.extend(modules)
        return tuple(all_modules)
    return ()


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
