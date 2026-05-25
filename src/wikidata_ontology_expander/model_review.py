from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

try:
    import requests
except ImportError:  # pragma: no cover - optional in offline/test environments
    requests = None

from .models import Change, ModelReviewConfig


@dataclass(frozen=True)
class ReviewDecision:
    accepted: bool
    confidence: float
    rationale: str
    normalized_label: str | None = None
    normalized_target_type: str | None = None
    normalized_value: str | None = None


class SchemaProposalReviewer:
    def review(self, proposal: Change) -> ReviewDecision:
        raise NotImplementedError


class NullSchemaProposalReviewer(SchemaProposalReviewer):
    def review(self, proposal: Change) -> ReviewDecision:
        return ReviewDecision(
            accepted=True,
            confidence=proposal.confidence,
            rationale="model review disabled",
            normalized_label=proposal.label,
            normalized_target_type=proposal.target_type,
            normalized_value=proposal.value,
        )


class OpenAIResponsesReviewer(SchemaProposalReviewer):
    def __init__(self, config: ModelReviewConfig):
        if requests is None:
            raise RuntimeError("requests is required to use model review")
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise RuntimeError(f"missing API key environment variable: {config.api_key_env}")
        self.config = config
        self.api_key = api_key

    def review(self, proposal: Change) -> ReviewDecision:
        url = urljoin(self.config.api_base.rstrip("/") + "/", "responses")
        prompt = _build_review_prompt(proposal)
        payload = {
            "model": self.config.model,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "schema_proposal_review",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "accepted": {"type": "boolean"},
                            "confidence": {"type": "number"},
                            "rationale": {"type": "string"},
                            "normalized_label": {"type": ["string", "null"]},
                            "normalized_target_type": {"type": ["string", "null"]},
                            "normalized_value": {"type": ["string", "null"]},
                        },
                        "required": [
                            "accepted",
                            "confidence",
                            "rationale",
                            "normalized_label",
                            "normalized_target_type",
                            "normalized_value",
                        ],
                    },
                }
            },
            "max_output_tokens": self.config.max_output_tokens,
            "temperature": self.config.temperature,
        }
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        text = _extract_output_text(data)
        parsed: dict[str, Any] = json.loads(text)
        return ReviewDecision(
            accepted=bool(parsed["accepted"]),
            confidence=float(parsed["confidence"]),
            rationale=str(parsed["rationale"]),
            normalized_label=parsed.get("normalized_label"),
            normalized_target_type=parsed.get("normalized_target_type"),
            normalized_value=parsed.get("normalized_value"),
        )


def build_reviewer(config: ModelReviewConfig | None) -> SchemaProposalReviewer:
    if config is None or not config.enabled:
        return NullSchemaProposalReviewer()
    if config.provider != "openai":
        raise ValueError(f"unsupported model review provider: {config.provider}")
    return OpenAIResponsesReviewer(config)


def _extract_output_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                return str(text)
    raise ValueError("Responses API payload did not contain output text")


def _build_review_prompt(proposal: Change) -> str:
    evidence_lines = [
        f"- {e.source}: {e.detail} (weight={e.weight})"
        for e in proposal.evidence
    ] or ["- no explicit evidence"]
    example_lines = [f"- {example}" for example in proposal.examples] or ["- no examples"]
    return f"""
You are reviewing an ontology schema expansion proposal.
Accept only if it adds schema-level knowledge that should likely be modeled in the ontology,
not merely an instance value or a trivial restatement.

Proposal action: {proposal.action}
Domain: {proposal.domain or ""}
Entity type: {proposal.entity_type}
Label: {proposal.label}
Field: {proposal.field or ""}
Value: {proposal.value or ""}
Target type: {proposal.target_type or ""}
Support count: {proposal.support}
Current confidence: {proposal.confidence}

Examples:
{chr(10).join(example_lines)}

Evidence:
{chr(10).join(evidence_lines)}

Return strict JSON.
Rules:
- Reject instance-level property values like descriptions, aliases, dates, URLs, or individual subclass links.
- Prefer normalized schema labels such as concept names, property names, and relation names.
- Keep rationale concise.
""".strip()
