import tempfile
import unittest
from pathlib import Path

from wikidata_ontology_expander.engine import ExpansionEngine
from wikidata_ontology_expander.models import (
    ExpansionConfig,
    ModuleProfile,
    SeedEntity,
    WikidataEntity,
    WikidataStatement,
)


class FakeClient:
    def search(self, term, limit=5):
        return [WikidataEntity(qid="Q123", label="Lithium-ion battery")]

    def get_entity(self, qid, properties=None):
        return WikidataEntity(
            qid=qid,
            label="Lithium-ion battery",
            description="rechargeable battery product",
            aliases=("Li-ion battery",),
            statements=(
                WikidataStatement("P31", "instance of", "Q28877", "battery"),
                WikidataStatement("P279", "subclass of", "Q28877", "battery"),
                WikidataStatement("P176", "manufacturer", "Q478214", "Panasonic"),
            ),
        )


class EngineTest(unittest.TestCase):
    def test_expand_generates_entity_property_and_relation_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
            schema_path.write_text(
                """
# 产品域

Product(Product): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
    description(Description): Text
  relations:
    #modules: hierarchy_relations
    subclassOf(Parent): Product
""",
                encoding="utf-8",
            )
            config = ExpansionConfig(
                min_accept_score=0.5,
                min_review_score=0.2,
                modules=(
                    ModuleProfile(
                        name="product",
                        entity_types=("Product",),
                        gate_properties=("P31", "P279"),
                        indicator_terms=("battery", "product"),
                        relation_properties={"subclassOf": "P279", "manufacturer": "P176"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config)
            changes = engine.expand(
                schema_path,
                [SeedEntity(name="lithium-ion battery", entity_type="Product", aliases=("Li-ion battery",))],
            )
            actions = {change.action for change in changes.changes}
            self.assertIn("enrich_existing", actions)
            self.assertIn("enrich_property", actions)
            self.assertIn("add_relation", actions)
            self.assertIsNotNone(changes.report)
            self.assertEqual(changes.report.classified_candidates, 1)
            self.assertEqual(changes.report.unclassified_candidates, 0)
            self.assertIn("product", changes.report.category_counts)

    def test_expand_corpus_routes_candidates_without_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
            schema_path.write_text(
                """
# 产品域

Product(Product): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
    description(Description): Text
  relations:
    #modules: hierarchy_relations
    subclassOf(Parent): Product
""",
                encoding="utf-8",
            )
            config = ExpansionConfig(
                min_accept_score=0.5,
                min_review_score=0.2,
                modules=(
                    ModuleProfile(
                        name="product",
                        entity_types=("Product",),
                        gate_properties=("P31", "P279"),
                        indicator_terms=("battery", "product"),
                        relation_properties={"subclassOf": "P279"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config)
            changes = engine.expand_corpus(
                schema_path,
                [
                    WikidataEntity(
                        qid="Q999",
                        label="Solid-state battery",
                        description="battery product",
                        statements=(
                            WikidataStatement("P31", "instance of", "Q28877", "battery"),
                            WikidataStatement("P279", "subclass of", "Q28877", "battery"),
                        ),
                    )
                ],
            )

            entity_changes = [change for change in changes.changes if change.wikidata_id == "Q999"]
            self.assertTrue(entity_changes)
            self.assertEqual(entity_changes[0].entity_type, "Product")
            self.assertEqual(changes.report.category_counts["product"], 1)


if __name__ == "__main__":
    unittest.main()
