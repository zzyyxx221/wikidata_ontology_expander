import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wikidata_ontology_expander.engine import load_config
from wikidata_ontology_expander.model_review import (
    NullSchemaProposalReviewer,
    OpenAIChatCompletionsReviewer,
    _parse_review_decision,
    _post_json,
    build_reviewer,
)
from wikidata_ontology_expander.models import Change, ModelReviewConfig


class FakeResponse:
    def __init__(self, payload=None, text="", status_error=None):
        self.payload = payload or {}
        self.text = text
        self.status_error = status_error

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_error is not None:
            raise self.status_error


class ModelReviewTest(unittest.TestCase):
    def _proposal(self):
        return Change(
            action="add_relation_type",
            entity_type="Product",
            label="Product",
            confidence=0.63,
            field="manufacturer",
            target_type="Enterprise",
            support=2,
            examples=("Battery -> manufacturer -> Panasonic",),
            source_entity_ids=("Q1",),
        )

    def test_null_reviewer_accepts_without_changes(self):
        reviewer = NullSchemaProposalReviewer()
        proposal = self._proposal()
        decision = reviewer.review(proposal)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.normalized_label, "Product")

    def test_openai_chat_provider_uses_chat_completions_endpoint(self):
        config = ModelReviewConfig(
            enabled=True,
            provider="openai_chat",
            model="local-model",
            api_base="http://10.130.138.46:8010",
        )
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "accepted": True,
                                "confidence": 0.82,
                                "rationale": "schema-level relation",
                                "normalized_label": "Product",
                                "normalized_target_type": "Enterprise",
                                "normalized_value": None,
                            }
                        )
                    }
                }
            ]
        }
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch(
            "wikidata_ontology_expander.model_review.requests.post",
            return_value=FakeResponse(payload),
        ) as post:
            reviewer = build_reviewer(config)
            self.assertIsInstance(reviewer, OpenAIChatCompletionsReviewer)
            decision = reviewer.review(self._proposal())

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.normalized_target_type, "Enterprise")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://10.130.138.46:8010/chat/completions")
        body = json.loads(kwargs["data"])
        self.assertEqual(body["model"], "local-model")
        self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_http_error_includes_response_body(self):
        import requests

        response = FakeResponse(text='{"error":"unsupported parameter: text.format"}')
        response.status_error = requests.HTTPError("400 Client Error: Bad Request")
        with patch("wikidata_ontology_expander.model_review.requests.post", return_value=response):
            with self.assertRaisesRegex(requests.HTTPError, "unsupported parameter"):
                _post_json("http://10.130.138.46:8010/responses", "test-key", {"model": "x"})

    def test_parse_review_decision_accepts_markdown_json_block(self):
        decision = _parse_review_decision(
            """
Here is the review:
```json
{
  "accepted": true,
  "confidence": 0.77,
  "rationale": "schema-level relation",
  "normalized_label": "Product",
  "normalized_target_type": "Enterprise",
  "normalized_value": null
}
```
"""
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.confidence, 0.77)
        self.assertEqual(decision.normalized_label, "Product")

    def test_parse_review_decision_rejects_empty_text_with_clear_error(self):
        with self.assertRaisesRegex(ValueError, "empty text"):
            _parse_review_decision("")

    def test_load_config_reads_model_review_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "seed.schema"
            config_path = root / "config.json"
            schema_path.write_text(
                """
# 产品域

Product(Product): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
""",
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps(
                    {
                        "modules": [{"name": "product", "entity_types": ["Product"], "gate_properties": ["P31"]}],
                        "model_review": {
                            "enabled": True,
                            "provider": "openai",
                            "model": "gpt-5-mini",
                            "api_key_env": "OPENAI_API_KEY",
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(config_path, schema_path)
            self.assertIsNotNone(config.model_review)
            assert config.model_review is not None
            self.assertTrue(config.model_review.enabled)
            self.assertEqual(config.model_review.model, "gpt-5-mini")


if __name__ == "__main__":
    unittest.main()
