import json
import tempfile
import unittest
from pathlib import Path

from wikidata_ontology_expander.models import Change, ChangeSet, Evidence
from wikidata_ontology_expander.refinement import apply_changeset_to_outputs, run_iterative_refinement


class RefinementTest(unittest.TestCase):
    def test_apply_changeset_updates_schema_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "seed.schema"
            config_path = root / "config.json"
            next_schema = root / "next.schema"
            next_config = root / "next.json"
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
                        "modules": [
                            {
                                "name": "product",
                                "entity_types": ["Product"],
                                "gate_properties": ["P31", "P279"],
                                "indicator_terms": ["battery", "product"],
                                "relation_properties": {},
                            }
                        ],
                        "property_map": {},
                    }
                ),
                encoding="utf-8",
            )
            changeset = ChangeSet(
                changes=[
                    Change(
                        action="add_category_gate",
                        entity_type="Product",
                        label="battery",
                        confidence=0.8,
                        domain="product",
                        field="instanceOf",
                        value="instance of",
                        target_type="gate_type",
                        support=1,
                    ),
                    Change(
                        action="add_relation_type",
                        entity_type="Product",
                        label="Product",
                        confidence=0.8,
                        domain="product",
                        module="supply_relations",
                        field="manufacturer",
                        value="manufacturer",
                        target_type="Enterprise",
                        support=1,
                        evidence=(Evidence("statement", "P176 / manufacturer", 0.2),),
                    ),
                ]
            )

            apply_changeset_to_outputs(schema_path, config_path, changeset, next_schema, next_config)

            rendered_schema = next_schema.read_text(encoding="utf-8")
            updated_config = json.loads(next_config.read_text(encoding="utf-8"))
            self.assertIn("manufacturer(Manufacturer): Enterprise", rendered_schema)
            self.assertIn("category_gate_labels", updated_config["modules"][0])
            self.assertIn("battery", updated_config["modules"][0]["category_gate_labels"])
            self.assertEqual(updated_config["modules"][0]["relation_properties"]["manufacturer"], "P176")

    def test_iterative_refinement_runs_multiple_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "seed.schema"
            config_path = root / "config.json"
            fixture_path = root / "fixture.json"
            output_dir = root / "runs"
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
                        "language": "en",
                        "min_accept_score": 0.5,
                        "min_review_score": 0.2,
                        "proposal_min_support": 1,
                        "property_map": {},
                        "modules": [
                            {
                                "name": "product",
                                "entity_types": ["Product"],
                                "gate_properties": ["P31", "P279"],
                                "indicator_terms": ["battery", "product"],
                                "relation_properties": {}
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            fixture_path.write_text(
                json.dumps(
                    {
                        "search": {},
                        "entities": [
                            {
                                "qid": "Q123",
                                "label": "Lithium-ion battery",
                                "description": "rechargeable battery product",
                                "aliases": ["Li-ion battery"],
                                "statements": [
                                    {"property_id": "P31", "property_label": "instance of", "value_id": "Q28877", "value_label": "battery"},
                                    {"property_id": "P279", "property_label": "subclass of", "value_id": "Q28877", "value_label": "battery"},
                                    {"property_id": "P176", "property_label": "manufacturer", "value_id": "Q478214", "value_label": "Panasonic"}
                                ]
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = run_iterative_refinement(
                mode="expand-corpus",
                schema_path=schema_path,
                config_path=config_path,
                output_dir=output_dir,
                rounds=2,
                accept_threshold=0.5,
                offline_fixture=fixture_path,
            )

            self.assertEqual(len(summary["rounds"]), 2)
            first_round = summary["rounds"][0]
            second_round = summary["rounds"][1]
            self.assertGreater(first_round["accepted"], 0)
            self.assertEqual(second_round["accepted"], 0)
            final_schema = Path(summary["final_schema"]).read_text(encoding="utf-8")
            self.assertIn("manufacturer(Manufacturer): Product", final_schema)


if __name__ == "__main__":
    unittest.main()
