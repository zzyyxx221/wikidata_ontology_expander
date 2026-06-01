from __future__ import annotations

import json
import os
import re
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
        try:
            response = _post_json(url, self.api_key, payload)
        except requests.HTTPError as exc:
            if _should_fallback_to_chat_completions(exc, self.config.api_base):
                return _review_with_chat_completions(self.config, self.api_key, proposal)
            raise
        data = response.json()
        text = _extract_output_text(data)
        return _parse_review_decision(text)


class OpenAIChatCompletionsReviewer(SchemaProposalReviewer):
    """Reviewer for OpenAI-compatible local servers that expose chat/completions."""

    def __init__(self, config: ModelReviewConfig):
        if requests is None:
            raise RuntimeError("requests is required to use model review")
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise RuntimeError(f"missing API key environment variable: {config.api_key_env}")
        self.config = config
        self.api_key = api_key

    def review(self, proposal: Change) -> ReviewDecision:
        return _review_with_chat_completions(self.config, self.api_key, proposal)


def build_reviewer(config: ModelReviewConfig | None) -> SchemaProposalReviewer:
    if config is None or not config.enabled:
        return NullSchemaProposalReviewer()
    if config.provider in {"openai", "openai_responses"}:
        return OpenAIResponsesReviewer(config)
    if config.provider in {"openai_chat", "openai-compatible", "openai_compatible", "litellm", "deepseek"}:
        return OpenAIChatCompletionsReviewer(config)
    raise ValueError(f"unsupported model review provider: {config.provider}")


def _review_with_chat_completions(
    config: ModelReviewConfig, api_key: str, proposal: Change
) -> ReviewDecision:
    url = urljoin(config.api_base.rstrip("/") + "/", "chat/completions")
    prompt = _build_review_prompt(proposal)
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": "Return only one strict JSON object with no markdown or explanation.",
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": config.max_output_tokens,
        "temperature": config.temperature,
    }
    response = _post_json(url, api_key, payload)
    data = response.json()
    text = _extract_chat_message_text(data)
    return _parse_review_decision(text)


def _post_json(url: str, api_key: str, payload: dict[str, Any]):
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=60,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text[:1000] if response.text else "<empty response body>"
        raise requests.HTTPError(f"{exc}; response body: {body}", response=response) from exc
    return response


def _should_fallback_to_chat_completions(exc: Exception, api_base: str) -> bool:
    response = getattr(exc, "response", None)
    if response is None or getattr(response, "status_code", None) != 404:
        return False
    normalized_base = api_base.rstrip("/").lower()
    return normalized_base not in {"https://api.openai.com/v1", "http://api.openai.com/v1"}


def _extract_output_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return str(payload["output_text"])
    for item in payload.get("output", []):
        for content in item.get("content", []):
            parsed = content.get("parsed")
            if isinstance(parsed, dict):
                return json.dumps(parsed)
            text = content.get("text")
            if text:
                return str(text)
            if content.get("type") == "refusal" and content.get("refusal"):
                raise ValueError(f"model refused schema proposal review: {content['refusal']}")
    raise ValueError("Responses API payload did not contain output text")


def _extract_chat_message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            parts = [str(part.get("text", "")) for part in content if isinstance(part, dict)]
            content = "".join(parts)
        if content:
            return str(content)
    raise ValueError("Chat Completions payload did not contain message content")


def _parse_review_decision(text: str) -> ReviewDecision:
    parsed = _find_review_decision_object(_loads_json_object(text))
    missing = [key for key in ("accepted", "confidence", "rationale") if key not in parsed]
    if missing:
        return ReviewDecision(
            accepted=False,
            confidence=0.0,
            rationale=f"model review returned JSON missing required fields: {', '.join(missing)}",
        )
    return ReviewDecision(
        accepted=_parse_bool(parsed["accepted"]),
        confidence=_parse_float(parsed["confidence"]),
        rationale=str(parsed["rationale"]),
        normalized_label=parsed.get("normalized_label"),
        normalized_target_type=parsed.get("normalized_target_type"),
        normalized_value=parsed.get("normalized_value"),
    )


def _loads_json_object(text: str) -> dict[str, Any]:
    candidate = _extract_json_object_text(text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        snippet = text[:500].replace("\n", "\\n")
        raise ValueError(f"model review returned invalid JSON: {exc}; text starts with: {snippet!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"model review JSON must be an object, got {type(parsed).__name__}")
    return parsed


def _extract_json_object_text(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        raise ValueError("model review returned empty text instead of JSON")

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.IGNORECASE | re.DOTALL)
    if fence_match:
        return fence_match.group(1)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def _find_review_decision_object(payload: dict[str, Any]) -> dict[str, Any]:
    if "accepted" in payload:
        return payload
    for key in ("review", "decision", "result", "schema_proposal_review"):
        value = payload.get(key)
        if isinstance(value, dict) and "accepted" in value:
            return value
    return payload


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "accept", "accepted"}:
            return True
        if lowered in {"false", "no", "0", "reject", "rejected"}:
            return False
    return bool(value)


def _parse_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
Required JSON shape:
{{
  "accepted": true,
  "confidence": 0.0,
  "rationale": "short reason",
  "normalized_label": null,
  "normalized_target_type": null,
  "normalized_value": null
}}
Rules:
- Reject instance-level property values like descriptions, aliases, dates, URLs, or individual subclass links.
- Prefer normalized schema labels such as concept names, property names, and relation names.
- Keep rationale concise.
""".strip()
