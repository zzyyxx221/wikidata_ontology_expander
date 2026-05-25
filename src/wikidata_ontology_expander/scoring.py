from __future__ import annotations

from dataclasses import dataclass

from .models import Evidence, ModuleProfile, SchemaModule, SeedEntity, WikidataEntity


@dataclass(frozen=True)
class ScoreResult:
    category: str | None
    score: float
    module: str | None
    category_score: float
    module_score: float
    evidence: tuple[Evidence, ...]


class GatePolicy:
    """Evidence-ranked classifier for domain and module routing."""

    def __init__(self, categories: tuple[ModuleProfile, ...]):
        self.categories = categories

    def classify(
        self,
        seed: SeedEntity,
        candidate: WikidataEntity,
        schema_modules: tuple[SchemaModule, ...] = (),
        relation_lookup: dict[str, str] | None = None,
        property_map: dict[str, str] | None = None,
        include_retrieval: bool = True,
    ) -> ScoreResult:
        seed_terms = [term.lower() for term in seed.search_terms]
        evidence: list[Evidence] = []

        retrieval_score = 0.0
        if include_retrieval:
            retrieval_score, retrieval_evidence = self._score_retrieval(seed_terms, candidate)
            evidence.extend(retrieval_evidence)

        category, category_score, category_evidence = self._score_category(seed, candidate)
        evidence.extend(category_evidence)

        module, module_score, module_evidence = self._score_module(
            category,
            seed,
            candidate,
            schema_modules,
            relation_lookup or {},
            property_map or {},
        )
        evidence.extend(module_evidence)

        total = min(retrieval_score + category_score + module_score, 1.0)
        return ScoreResult(
            category=category,
            score=total,
            module=module,
            category_score=category_score,
            module_score=module_score,
            evidence=tuple(evidence),
        )

    def score(
        self,
        seed: SeedEntity,
        candidate: WikidataEntity,
        schema_modules: tuple[SchemaModule, ...] = (),
        relation_lookup: dict[str, str] | None = None,
        property_map: dict[str, str] | None = None,
    ) -> ScoreResult:
        return self.classify(seed, candidate, schema_modules, relation_lookup, property_map)

    def _score_retrieval(self, seed_terms: list[str], candidate: WikidataEntity) -> tuple[float, list[Evidence]]:
        evidence: list[Evidence] = []
        score = 0.0

        label = candidate.label.lower()
        if label in seed_terms:
            score += 0.42
            evidence.append(Evidence("label", f"exact label match: {candidate.label}", 0.42))
        elif any(term in label or label in term for term in seed_terms):
            score += 0.25
            evidence.append(Evidence("label", f"partial label match: {candidate.label}", 0.25))

        alias_hits = set(a.lower() for a in candidate.aliases) & set(seed_terms)
        if alias_hits:
            score += 0.18
            evidence.append(Evidence("alias", f"alias match: {', '.join(sorted(alias_hits))}", 0.18))

        if candidate.description:
            description = candidate.description.lower()
            hits = [term for term in seed_terms if term and term in description]
            if hits:
                score += 0.1
                evidence.append(Evidence("description", f"description contains: {', '.join(hits)}", 0.1))

        return min(score, 1.0), evidence

    def _score_category(
        self, seed: SeedEntity, candidate: WikidataEntity
    ) -> tuple[str | None, float, list[Evidence]]:
        statement_pids = {s.property_id for s in candidate.statements}
        haystack = f"{candidate.label} {candidate.description}".lower()

        best_name: str | None = None
        best_score = 0.0
        best_evidence: list[Evidence] = []

        for category in self.categories:
            evidence: list[Evidence] = []
            score = 0.0
            gate_hits = statement_pids & set(category.gate_properties)
            if gate_hits:
                weight = min(0.56, 0.2 * len(gate_hits))
                score += weight
                evidence.append(Evidence("category_gate", f"gate properties: {', '.join(sorted(gate_hits))}", weight))

            indicator_hits = [term for term in category.indicator_terms if term.lower() in haystack]
            if indicator_hits:
                weight = min(0.25, 0.08 * len(indicator_hits))
                score += weight
                evidence.append(Evidence("category_indicator", f"module terms: {', '.join(indicator_hits)}", weight))

            gate_label_hits = []
            configured_gate_labels = {label.lower() for label in category.category_gate_labels}
            if configured_gate_labels:
                for statement in candidate.statements:
                    if statement.property_id not in {"P31", "P279"}:
                        continue
                    if statement.value_label.lower() in configured_gate_labels:
                        gate_label_hits.append(statement.value_label)
                if gate_label_hits:
                    weight = min(0.4, 0.16 * len(set(gate_label_hits)))
                    score += weight
                    evidence.append(
                        Evidence(
                            "category_gate_label",
                            f"gate labels: {', '.join(sorted(set(gate_label_hits)))}",
                            weight,
                        )
                    )

            if seed.entity_type and category.entity_types and seed.entity_type in category.entity_types:
                weight = 0.08
                score += weight
                evidence.append(Evidence("category_type", f"seed entity type: {seed.entity_type}", weight))

            if score > best_score:
                best_name = category.name
                best_score = score
                best_evidence = evidence

        return best_name, best_score, best_evidence

    def _score_module(
        self,
        category_name: str | None,
        seed: SeedEntity,
        candidate: WikidataEntity,
        schema_modules: tuple[SchemaModule, ...],
        relation_lookup: dict[str, str],
        property_map: dict[str, str],
    ) -> tuple[str | None, float, list[Evidence]]:
        if category_name is None:
            best_name: str | None = None
            best_score = 0.0
            best_evidence: list[Evidence] = []
            category_modules = schema_modules
        else:
            best_name = None
            best_score = 0.0
            best_evidence = []
            category_modules = [module for module in schema_modules if module.domain == category_name]

        statement_pids = {s.property_id for s in candidate.statements}
        haystack = f"{candidate.label} {candidate.description}".lower()

        for module in category_modules:
            evidence: list[Evidence] = []
            module_score = 0.0
            if module.kind in ("intrinsic", "mixed"):
                prop_hits: list[str] = []
                for field_name in module.property_fields:
                    pid = property_map.get(field_name)
                    if pid and pid in statement_pids:
                        prop_hits.append(pid)
                if prop_hits:
                    weight = min(0.22, 0.05 * len(prop_hits))
                    module_score += weight
                    evidence.append(Evidence("property", f"property fields: {', '.join(sorted(prop_hits))}", weight))

                field_hits = [field for field in module.property_fields if field.lower() in haystack]
                if field_hits:
                    weight = min(0.12, 0.04 * len(field_hits))
                    module_score += weight
                    evidence.append(Evidence("indicator", f"schema fields: {', '.join(field_hits)}", weight))

            if module.kind in ("relational", "mixed"):
                relation_hits: list[str] = []
                for field_name in module.relation_fields:
                    pid = relation_lookup.get(field_name)
                    if pid and pid in statement_pids:
                        relation_hits.append(pid)
                if relation_hits:
                    weight = min(0.3, 0.08 * len(relation_hits))
                    module_score += weight
                    evidence.append(Evidence("relation", f"relation fields: {', '.join(sorted(relation_hits))}", weight))

            if seed.entity_type and module.entity_types and seed.entity_type in module.entity_types:
                weight = 0.06
                module_score += weight
                evidence.append(Evidence("module_type", f"seed entity type: {seed.entity_type}", weight))

            if module_score > best_score:
                best_name = module.name
                best_score = module_score
                best_evidence = evidence

        return best_name, best_score, best_evidence
