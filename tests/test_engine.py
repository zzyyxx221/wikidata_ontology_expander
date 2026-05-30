import tempfile
import unittest
from pathlib import Path

from wikidata_ontology_expander.engine import ExpansionEngine
from wikidata_ontology_expander.models import (
    EntityTypeRule,
    ExpansionConfig,
    ModuleProfile,
    SeedEntity,
    WikidataEntity,
    WikidataStatement,
)
from wikidata_ontology_expander.taxonomy import TaxonomyNode, TaxonomyReference


class FakeClient:
    def search(self, term, limit=5):
        return [WikidataEntity(source_id="Q123", label="Lithium-ion battery")]

    def get_entity(self, source_id, properties=None):
        return WikidataEntity(
            source_id=source_id,
            label="Lithium-ion battery",
            description="rechargeable battery product",
            aliases=("Li-ion battery",),
            statements=(
                WikidataStatement("P31", "instance of", "Q28877", "battery"),
                WikidataStatement("P279", "subclass of", "Q28877", "battery"),
                WikidataStatement("P176", "manufacturer", "Q478214", "Panasonic"),
                WikidataStatement("P186", "made from material", "Q568", "lithium"),
            ),
        )


class EngineTest(unittest.TestCase):
    def test_expand_generates_schema_level_proposals_only(self):
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
    #modules: supply_relations
    rawMaterial(Raw material): Product
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
                        relation_properties={"subclassOf": "P279", "manufacturer": "P176", "rawMaterial": "P186"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config)
            changes = engine.expand(
                schema_path,
                [SeedEntity(name="lithium-ion battery", entity_type="Product", aliases=("Li-ion battery",))],
            )
            actions = {change.action for change in changes.changes}
            self.assertIn("add_relation_type", actions)
            self.assertNotIn("enrich_property", actions)
            self.assertNotIn("add_relation", actions)
            self.assertNotIn("add_concept", actions)

            manufacturer_change = next(
                change
                for change in changes.changes
                if change.action == "add_relation_type" and change.field == "manufacturer"
            )
            self.assertEqual(manufacturer_change.target_type, "Enterprise")
            self.assertEqual(manufacturer_change.module, "product")
            self.assertGreaterEqual(manufacturer_change.support, 1)

            raw_material_changes = [change for change in changes.changes if change.field == "rawMaterial"]
            self.assertFalse(raw_material_changes)

    def test_expand_corpus_proposes_new_slots_not_instance_values(self):
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
                        relation_properties={"subclassOf": "P279", "rawMaterial": "P186"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config)
            changes = engine.expand_corpus(
                schema_path,
                [
                    WikidataEntity(
                        source_id="Q999",
                        label="Solid-state battery",
                        description="battery product",
                        statements=(
                            WikidataStatement("P31", "instance of", "Q28877", "battery"),
                            WikidataStatement("P279", "subclass of", "Q28877", "battery"),
                            WikidataStatement("P186", "made from material", "Q111", "ceramic"),
                        ),
                    )
                ],
            )

            slot_changes = [change for change in changes.changes if change.action == "add_relation_type"]
            self.assertTrue(slot_changes)
            self.assertEqual(slot_changes[0].field, "rawMaterial")
            self.assertEqual(changes.report.category_counts["product"], 1)

    def test_new_relation_type_binds_to_scored_module_when_schema_has_no_specific_field_module(self):
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
    #modules: supply_relations
    rawMaterial(Raw material): Product
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
                        gate_properties=("P31", "P176"),
                        indicator_terms=("product", "battery"),
                        relation_properties={"manufacturer": "P176"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config)
            changes = engine.expand(
                schema_path,
                [SeedEntity(name="lithium-ion battery", entity_type="Product", aliases=("Li-ion battery",))],
            )
            manufacturer_change = next(
                change
                for change in changes.changes
                if change.action == "add_relation_type" and change.field == "manufacturer"
            )
            self.assertEqual(manufacturer_change.module, "product")

    def test_expand_filters_duplicate_or_instance_like_concepts(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
            schema_path.write_text(
                """
# 企业域

Enterprise(Enterprise): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
""",
                encoding="utf-8",
            )
            config = ExpansionConfig(
                min_accept_score=0.5,
                min_review_score=0.2,
                modules=(
                    ModuleProfile(
                        name="enterprise",
                        entity_types=("Enterprise",),
                        gate_properties=("P31", "P452", "P856"),
                        indicator_terms=("company", "enterprise"),
                        relation_properties={"industry": "P452"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClientEnterprise(), config)
            changes = engine.expand(
                schema_path,
                [SeedEntity(name="Tesla, Inc.", entity_type="Enterprise", aliases=("Tesla",))],
            )
            self.assertFalse([change for change in changes.changes if change.action == "add_concept"])
            self.assertTrue([change for change in changes.changes if change.action == "add_relation_type"])

    def test_expand_does_not_add_seed_child_as_schema_concept(self):
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
            engine = ExpansionEngine(FakeClientSolidStateBattery(), config)
            changes = engine.expand(
                schema_path,
                [SeedEntity(name="lithium-ion battery", entity_type="Product", parent="Battery")],
            )

            self.assertFalse([change for change in changes.changes if change.action == "add_concept"])

    def test_configured_domain_relation_field_prevents_global_pid_misnaming(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
            schema_path.write_text(
                """
# 企业域

Enterprise(Enterprise): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
  relations:
    #modules: classification_relations
    belongsToIndustry(Industry): Industry
""",
                encoding="utf-8",
            )
            config = ExpansionConfig(
                min_accept_score=0.5,
                min_review_score=0.2,
                modules=(
                    ModuleProfile(
                        name="enterprise",
                        entity_types=("Enterprise",),
                        gate_properties=("P31", "P452"),
                        indicator_terms=("company",),
                        relation_properties={"belongsToIndustry": "P452"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClientEnterprise(), config)
            changes = engine.expand(
                schema_path,
                [SeedEntity(name="Tesla, Inc.", entity_type="Enterprise", aliases=("Tesla",))],
            )

            self.assertFalse([change for change in changes.changes if change.field == "industry"])

    def test_region_relations_route_to_schema_relation_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
            schema_path.write_text(
                """
# 区域域

Region(Region): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
  relations:
    #modules: administrative_relations
    locatedInAdministrativeEntity(Located in): Region
""",
                encoding="utf-8",
            )
            config = ExpansionConfig(
                min_accept_score=0.5,
                min_review_score=0.2,
                modules=(
                    ModuleProfile(
                        name="region",
                        entity_types=("Region",),
                        gate_properties=("P31", "P131"),
                        indicator_terms=("municipality", "city", "region"),
                        relation_properties={"locatedInAdministrativeEntity": "P131"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClientRegion(), config)
            changes = engine.expand(
                schema_path,
                [SeedEntity(name="Shanghai", entity_type="Region", aliases=("Shanghai Municipality",))],
            )
            self.assertEqual(changes.report.category_counts["region"], 1)
            self.assertFalse([change for change in changes.changes if change.field == "locatedInAdministrativeEntity"])

    def test_expand_corpus_deduplicates_same_schema_proposal_across_distinct_source_ids(self):
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
""",
                encoding="utf-8",
            )
            config = ExpansionConfig(
                min_accept_score=0.5,
                min_review_score=0.2,
                proposal_min_support=1,
                modules=(
                    ModuleProfile(
                        name="product",
                        entity_types=("Product",),
                        gate_properties=("P31", "P279"),
                        indicator_terms=("battery", "product"),
                        relation_properties={"subclassOf": "P279", "rawMaterial": "P186"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config)
            changes = engine.expand_corpus(
                schema_path,
                [
                    WikidataEntity(
                        source_id="Q999",
                        label="Solid-state battery",
                        description="battery product",
                        statements=(
                            WikidataStatement("P31", "instance of", "Q28877", "battery"),
                            WikidataStatement("P279", "subclass of", "Q28877", "battery"),
                            WikidataStatement("P186", "made from material", "Q111", "ceramic"),
                        ),
                    ),
                    WikidataEntity(
                        source_id="Q1000",
                        label="Sodium-ion battery",
                        description="battery product",
                        statements=(
                            WikidataStatement("P31", "instance of", "Q28877", "battery"),
                            WikidataStatement("P279", "subclass of", "Q28877", "battery"),
                            WikidataStatement("P186", "made from material", "Q222", "sodium"),
                        ),
                    ),
                ],
            )

            slot_changes = [change for change in changes.changes if change.action == "add_relation_type"]
            self.assertEqual(len(slot_changes), 1)
            self.assertEqual(slot_changes[0].field, "rawMaterial")
            self.assertEqual(slot_changes[0].support, 2)
            self.assertEqual(slot_changes[0].source_entity_ids, ("Q999", "Q1000"))

    def test_expand_corpus_proposes_category_gate_for_unclassified_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
            schema_path.write_text(
                """
# 企业域

Enterprise(Enterprise): EntityType
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
                modules=(
                    ModuleProfile(
                        name="enterprise",
                        entity_types=("Enterprise",),
                        gate_properties=("P452", "P856"),
                        indicator_terms=("company", "enterprise"),
                        relation_properties={"industry": "P452"},
                    ),
                    ModuleProfile(
                        name="technology",
                        entity_types=("Technology",),
                        gate_properties=(),
                        indicator_terms=(),
                        relation_properties={"subclassOf": "P279"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config)
            changes = engine.expand_corpus(
                schema_path,
                [
                    WikidataEntity(
                        source_id="Q183907",
                        label="Photolithography",
                        description="manufacturing process used in semiconductor fabrication",
                        statements=(
                            WikidataStatement("P31", "instance of", "Q2995644", "manufacturing process"),
                            WikidataStatement("P279", "subclass of", "Q11023", "engineering"),
                        ),
                    )
                ],
            )

            gate_changes = [change for change in changes.changes if change.action == "add_category_gate"]
            self.assertTrue(gate_changes)
            self.assertEqual(gate_changes[0].domain, "technology")
            self.assertEqual(gate_changes[0].field, "instanceOf")
            self.assertEqual(gate_changes[0].label, "manufacturing process")

    def test_expand_corpus_proposes_module_for_category_matches_without_module_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
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
            config = ExpansionConfig(
                min_accept_score=0.5,
                min_review_score=0.2,
                proposal_min_support=1,
                modules=(
                    ModuleProfile(
                        name="product",
                        entity_types=("Product",),
                        gate_properties=("P31", "P279"),
                        indicator_terms=("battery", "product"),
                        relation_properties={"manufacturer": "P176"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config)
            changes = engine.expand_corpus(
                schema_path,
                [
                    WikidataEntity(
                        source_id="Q123",
                        label="Lithium-ion battery",
                        description="rechargeable battery product",
                        aliases=("Li-ion battery",),
                        statements=(
                            WikidataStatement("P31", "instance of", "Q28877", "battery"),
                            WikidataStatement("P279", "subclass of", "Q28877", "battery"),
                            WikidataStatement("P176", "manufacturer", "Q478214", "Panasonic"),
                            WikidataStatement("P186", "made from material", "Q568", "lithium"),
                        ),
                    )
                ],
            )

            module_changes = [change for change in changes.changes if change.action == "add_module"]
            self.assertTrue(module_changes)
            self.assertEqual(module_changes[0].domain, "product")
            self.assertIn("manufacturer_relations", {change.module for change in module_changes})
            self.assertTrue(any(change.target_type == "relational" for change in module_changes))

    def test_taxonomy_reference_freezes_top_level_but_allows_slot_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
            schema_path.write_text(
                """
# 产品域

Product(标准产品): EntityType
  properties:
    #modules: common_properties
    name(名称): Text
  relations:
    #modules: hierarchy_relations
    subclassOf(上位产品): Product
""",
                encoding="utf-8",
            )
            taxonomy = TaxonomyReference(
                (
                    TaxonomyNode(
                        code="EC001001020101020502",
                        label="镍钴锰酸锂",
                        entity_type="Product",
                        domain="product",
                        level=9,
                        parent_code="EC0010010201010205",
                    ),
                )
            )
            config = ExpansionConfig(
                freeze_top_level_schema=True,
                allowed_schema_actions=("add_module", "add_property_type", "add_relation_type"),
                min_accept_score=0.5,
                min_review_score=0.2,
                proposal_min_support=1,
                modules=(
                    ModuleProfile(
                        name="product",
                        entity_types=("Product",),
                        gate_properties=("P31", "P279"),
                        indicator_terms=("product", "battery", "正极材料"),
                        relation_properties={"subclassOf": "P279", "manufacturer": "P176"},
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config, taxonomy_reference=taxonomy)
            changes = engine.expand_corpus(
                schema_path,
                [
                    WikidataEntity(
                        source_id="QCN001",
                        label="镍钴锰酸锂",
                        description="锂离子电池正极材料 product",
                        aliases=("NCM cathode material",),
                        statements=(
                            WikidataStatement("P31", "instance of", "Q1", "product"),
                            WikidataStatement("P176", "manufacturer", "Q2", "CATL"),
                            WikidataStatement("P9001", "nominal voltage", None, "3.7 V"),
                        ),
                    )
                ],
            )

            actions = {change.action for change in changes.changes}
            self.assertNotIn("add_concept", actions)
            self.assertNotIn("add_category_gate", actions)
            self.assertIn("add_relation_type", actions)
            self.assertIn("add_property_type", actions)
            self.assertTrue([change for change in changes.changes if change.action == "add_module"])
            self.assertTrue(
                any(
                    evidence.source == "taxonomy_reference"
                    for change in changes.changes
                    for evidence in change.evidence
                )
            )

    def test_entity_type_rules_from_config_override_domain_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_path = Path(tmp) / "seed.schema"
            schema_path.write_text(
                """
# 产品域

Product(Product): EntityType
  properties:
    #modules: common_properties
    name(Name): Text

ProductModel(Product model): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
""",
                encoding="utf-8",
            )
            config = ExpansionConfig(
                min_accept_score=0.5,
                min_review_score=0.2,
                modules=(
                    ModuleProfile(
                        name="product",
                        entity_types=("Product", "ProductModel"),
                        gate_properties=("P31",),
                        indicator_terms=("accelerator",),
                        entity_type_rules=(
                            EntityTypeRule("ProductModel", ("accelerator model", "H100")),
                        ),
                    ),
                ),
            )
            engine = ExpansionEngine(FakeClient(), config)
            changes = engine.expand_corpus(
                schema_path,
                [
                    WikidataEntity(
                        source_id="QH100",
                        label="NVIDIA H100",
                        description="GPU accelerator model",
                        statements=(WikidataStatement("P31", "instance of", "Q1", "product"),),
                    )
                ],
            )

            self.assertTrue(changes.changes)
            self.assertTrue(all(change.entity_type == "ProductModel" for change in changes.changes))


class FakeClientEnterprise:
    def search(self, term, limit=5):
        return [WikidataEntity(source_id="Q478214", label="Tesla, Inc.")]

    def get_entity(self, source_id, properties=None):
        return WikidataEntity(
            source_id=source_id,
            label="Tesla, Inc.",
            description="American automotive company",
            aliases=("Tesla",),
            statements=(
                WikidataStatement("P31", "instance of", "Q4830453", "business"),
                WikidataStatement("P452", "industry", "Q190117", "automotive industry"),
                WikidataStatement("P856", "official website", None, "https://www.tesla.com/"),
            ),
        )


class FakeClientSolidStateBattery:
    def search(self, term, limit=5):
        return [WikidataEntity(source_id="Q999002", label="solid-state battery")]

    def get_entity(self, source_id, properties=None):
        return WikidataEntity(
            source_id=source_id,
            label="solid-state battery",
            description="battery product using a solid electrolyte",
            statements=(
                WikidataStatement("P31", "instance of", "Q28877", "battery"),
                WikidataStatement("P279", "subclass of", "Q28877", "battery"),
            ),
        )


class FakeClientRegion:
    def search(self, term, limit=5):
        return [WikidataEntity(source_id="Q8686", label="Shanghai")]

    def get_entity(self, source_id, properties=None):
        return WikidataEntity(
            source_id=source_id,
            label="Shanghai",
            description="provincial-level municipality in China",
            aliases=("Shanghai Municipality",),
            statements=(
                WikidataStatement("P31", "instance of", "Q13218391", "municipality of China"),
                WikidataStatement("P131", "located in administrative territorial entity", "Q148", "China"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
