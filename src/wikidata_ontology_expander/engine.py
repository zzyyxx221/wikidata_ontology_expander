from __future__ import annotations

import json
from pathlib import Path

from .models import (
    Change,
    ChangeSet,
    ExpansionConfig,
    ModuleProfile,
    SeedEntity,
    WikidataEntity,
)
from .schema_parser import parse_schema
from .scoring import GatePolicy
from .wikidata import WikidataClient


class ExpansionEngine:
    def __init__(self, client: WikidataClient, config: ExpansionConfig):
        self.client = client
        self.config = config
        self.gate = GatePolicy(config.modules)

    def expand(self, schema_path: Path, seeds: list[SeedEntity]) -> ChangeSet:
        schema = parse_schema(schema_path)
        changeset = ChangeSet()
        known_labels = {seed.name.lower() for seed in seeds}
        known_labels.update(entity.label.lower() for entity in schema.values() if entity.label)

        properties = self._properties_to_fetch()
        for seed in seeds:
            seen_qids: set[str] = set()
            for term in seed.search_terms:
                remaining = self.config.max_candidates_per_seed - len(seen_qids)
                if remaining <= 0:
                    break
                for candidate in self.client.search(term, limit=remaining):
                    if candidate.qid in seen_qids:
                        continue
                    seen_qids.add(candidate.qid)
                    if len(seen_qids) > self.config.max_candidates_per_seed:
                        break
                    enriched = self.client.get_entity(candidate.qid, properties=properties)
                    scored = self.gate.score(seed, enriched)
                    if scored.score < self.config.min_review_score:
                        continue

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
                    self._add_property_enrichment(changeset, seed, enriched, scored.score, review_required)
                    self._add_relation_expansion(changeset, seed, enriched, scored.score, review_required)
        return changeset

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
    ) -> None:
        if entity.description:
            changeset.add(
                Change(
                    action="enrich_property",
                    entity_type=seed.entity_type,
                    label=entity.label,
                    wikidata_id=entity.qid,
                    confidence=round(min(base_score, 0.95), 4),
                    module=seed.module,
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
                    module=seed.module,
                    field="alias",
                    value="; ".join(entity.aliases[:8]),
                    review_required=review_required,
                )
            )
        for field_name, pid in self.config.property_map.items():
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
                    module=seed.module,
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
    ) -> None:
        for module in self.config.modules:
            if seed.entity_type not in module.entity_types:
                continue
            for relation_name, pid in module.relation_properties.items():
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


def load_config(path: Path) -> ExpansionConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    modules = tuple(
        ModuleProfile(
            name=item["name"],
            entity_types=tuple(item.get("entity_types", [])),
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
