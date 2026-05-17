from __future__ import annotations

from dataclasses import dataclass

from .models import Evidence, ModuleProfile, SeedEntity, WikidataEntity


@dataclass(frozen=True)
class ScoreResult:
    score: float
    module: str | None
    evidence: tuple[Evidence, ...]


class GatePolicy:
    """Scores Wikidata candidates against seed terms and module indicators."""

    def __init__(self, modules: tuple[ModuleProfile, ...]):
        self.modules = modules

    def score(self, seed: SeedEntity, candidate: WikidataEntity) -> ScoreResult:
        evidence: list[Evidence] = []
        score = 0.0

        label = candidate.label.lower()
        seed_terms = [term.lower() for term in seed.search_terms]
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

        module, module_score, module_evidence = self._score_module(seed, candidate)
        score += module_score
        evidence.extend(module_evidence)

        if candidate.description:
            description = candidate.description.lower()
            hits = [term for term in seed_terms if term and term in description]
            if hits:
                score += 0.1
                evidence.append(Evidence("description", f"description contains: {', '.join(hits)}", 0.1))

        return ScoreResult(score=min(score, 1.0), module=module, evidence=tuple(evidence))

    def _score_module(
        self, seed: SeedEntity, candidate: WikidataEntity
    ) -> tuple[str | None, float, list[Evidence]]:
        best_module = seed.module
        best_score = 0.0
        best_evidence: list[Evidence] = []

        for module in self.modules:
            module_score = 0.0
            evidence: list[Evidence] = []
            if seed.entity_type in module.entity_types:
                module_score += 0.12
                evidence.append(Evidence("module", f"seed type belongs to module {module.name}", 0.12))

            statement_pids = {s.property_id for s in candidate.statements}
            gate_hits = statement_pids & set(module.gate_properties)
            if gate_hits:
                weight = min(0.24, 0.08 * len(gate_hits))
                module_score += weight
                evidence.append(Evidence("gate", f"gate properties: {', '.join(sorted(gate_hits))}", weight))

            haystack = f"{candidate.label} {candidate.description}".lower()
            term_hits = [term for term in module.indicator_terms if term.lower() in haystack]
            if term_hits:
                weight = min(0.18, 0.06 * len(term_hits))
                module_score += weight
                evidence.append(Evidence("indicator", f"module terms: {', '.join(term_hits)}", weight))

            if module_score > best_score:
                best_score = module_score
                best_module = module.name
                best_evidence = evidence

        return best_module, best_score, best_evidence

