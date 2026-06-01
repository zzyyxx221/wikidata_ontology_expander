import json
import tempfile
import unittest
from pathlib import Path

from wikidata_ontology_expander.engine import ExpansionEngine
from wikidata_ontology_expander.fixture_client import FixtureWikidataClient
from wikidata_ontology_expander.models import ExpansionConfig, ModuleProfile


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_FIXTURE = ROOT / "examples" / "offline_wikidata_fixture_taxonomy.json"


class TaxonomyFixtureTest(unittest.TestCase):
    def test_taxonomy_fixture_search_index_covers_new_examples(self):
        data = json.loads(TAXONOMY_FIXTURE.read_text(encoding="utf-8"))
        qids = {item["qid"] for item in data["entities"]}
        self.assertEqual(len(qids), len(data["entities"]))
        for term, search_qids in data["search"].items():
            self.assertTrue(search_qids, term)
            self.assertTrue(set(search_qids).issubset(qids), term)

        client = FixtureWikidataClient(TAXONOMY_FIXTURE)
        self.assertEqual(client.search("solid-state battery")[0].source_id, "QTX006")
        self.assertEqual(client.search("sic mosfet")[0].label, "碳化硅MOSFET")
        self.assertEqual(client.search("drug discovery cro service")[0].source_id, "QTX012")

    def test_taxonomy_fixture_expands_to_new_product_industry_and_service_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
            schema_path.write_text(
                """
# 产品域

Product(Product): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
  relations:
    #modules: hierarchy_relations
    subclassOf(Parent): Product

Industry(Industry): EntityType
  properties:
    #modules: common_properties
    name(Name): Text

Service(Service): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
""",
                encoding="utf-8",
            )
            config = ExpansionConfig(
                min_accept_score=0.5,
                min_review_score=0.2,
                proposal_min_support=1,
                allowed_schema_actions=(
                    "add_module",
                    "add_property_type",
                    "add_relation_type",
                    "add_category_gate",
                ),
                modules=(
                    ModuleProfile(
                        name="product",
                        entity_types=("Product",),
                        gate_properties=("P31", "P279", "P176", "P186", "P527"),
                        category_gate_labels=(
                            "product",
                            "battery",
                            "semiconductor device",
                            "equipment",
                        ),
                        indicator_terms=("product", "battery", "material", "equipment", "component", "robot"),
                        relation_properties={
                            "subclassOf": "P279",
                            "manufacturer": "P176",
                            "rawMaterial": "P186",
                            "component": "P527",
                        },
                    ),
                    ModuleProfile(
                        name="industry",
                        entity_types=("Industry",),
                        gate_properties=("P31", "P279", "P452"),
                        category_gate_labels=("industry", "manufacturing industry"),
                        indicator_terms=("industry", "sector", "manufacturing"),
                        relation_properties={"subclassOf": "P279", "belongsToIndustry": "P452"},
                    ),
                    ModuleProfile(
                        name="service",
                        entity_types=("Service",),
                        gate_properties=("P31", "P452", "P178"),
                        category_gate_labels=("service",),
                        indicator_terms=("service", "outsourcing", "organization"),
                        relation_properties={"developer": "P178", "belongsToIndustry": "P452"},
                    ),
                ),
            )
            client = FixtureWikidataClient(TAXONOMY_FIXTURE)
            changeset = ExpansionEngine(client, config).expand_corpus(schema_path, client.all_entities())

        fields = {change.field for change in changeset.changes}
        self.assertGreaterEqual(len(changeset.changes), 40)
        self.assertEqual(changeset.report.category_counts["product"], 15)
        self.assertEqual(changeset.report.category_counts["industry"], 1)
        self.assertEqual(changeset.report.category_counts["service"], 4)
        self.assertTrue(
            {
                "energyDensity",
                "breakdownVoltage",
                "payloadCapacity",
                "capitalIntensity",
                "assayType",
            }.issubset(fields)
        )


if __name__ == "__main__":
    unittest.main()
