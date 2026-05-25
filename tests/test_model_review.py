import json
import tempfile
import unittest
from pathlib import Path

from wikidata_ontology_expander.engine import load_config
from wikidata_ontology_expander.model_review import NullSchemaProposalReviewer
from wikidata_ontology_expander.models import Change


class ModelReviewTest(unittest.TestCase):
    def test_null_reviewer_accepts_without_changes(self):
        reviewer = NullSchemaProposalReviewer()
        proposal = Change(
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
        decision = reviewer.review(proposal)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.normalized_label, "Product")

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
