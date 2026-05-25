import unittest

from wikidata_ontology_expander.models import ModuleProfile, SeedEntity, WikidataEntity, WikidataStatement
from wikidata_ontology_expander.scoring import GatePolicy


class GatePolicyTest(unittest.TestCase):
    def test_category_with_stronger_evidence_wins(self):
        policy = GatePolicy(
            (
                ModuleProfile(name="first", entity_types=("Product",), gate_properties=("P31",)),
                ModuleProfile(
                    name="second",
                    entity_types=("Product",),
                    gate_properties=("P31",),
                    indicator_terms=("battery",),
                ),
            )
        )
        seed = SeedEntity(name="battery", entity_type="Product")
        candidate = WikidataEntity(
            source_id="Q1",
            label="Battery",
            description="rechargeable battery",
            statements=(WikidataStatement("P31", "instance of", "Q1", "battery"),),
        )

        scored = policy.classify(seed, candidate)

        self.assertEqual(scored.category, "second")
        self.assertGreater(scored.category_score, 0.0)
        self.assertEqual(scored.module, None)


if __name__ == "__main__":
    unittest.main()
