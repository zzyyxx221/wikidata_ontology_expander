import tempfile
import unittest
from pathlib import Path

from wikidata_ontology_expander.schema_parser import load_schema_document, parse_schema_document, parse_schema_text, schema_cache_path


class SchemaParserTest(unittest.TestCase):
    def test_parse_entity_fields_and_modules(self):
        text = """
namespace Demo

Product(Product): EntityType
  properties:
    #modules: common_properties
    name(Name): Text
      index: Text
    #modules: lifecycle_properties
    publishDate(Publish date): STD.Date
      constraint: MultiValue

  relations:
    #modules: hierarchy_relations
    subclassOf(Parent product): Product
"""
        schema = parse_schema_text(text)
        product = schema["Product"]
        self.assertEqual(product.kind, "EntityType")
        self.assertEqual(len(product.fields), 3)
        self.assertEqual(product.fields[1].module, "lifecycle_properties")
        self.assertEqual(product.fields[1].constraints, ("MultiValue",))
        self.assertEqual(product.fields[2].section, "relation")

    def test_parse_domains_from_section_headings(self):
        text = """
# 产业域

Industry(行业): EntityType
  properties:
    #modules: common_properties
    name(名称): Text

# 产品域

Product(标准产品): EntityType
  properties:
    #modules: common_properties
    name(名称): Text
"""
        doc = parse_schema_document(text)
        self.assertEqual([domain.key for domain in doc.domains], ["industry", "product"])
        self.assertEqual(doc.entities["Industry"].domain, "industry")
        self.assertEqual(doc.entities["Product"].domain, "product")

    def test_load_schema_document_caches_parsed_domain_and_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = root / "seed.schema"
            cache_dir = root / "cache"
            schema_path.write_text(
                """
# 产品域

Product(标准产品): EntityType
  properties:
    #modules: common_properties
    name(名称): Text
""",
                encoding="utf-8",
            )

            first = load_schema_document(schema_path, cache_dir=cache_dir)
            cache_path = schema_cache_path(schema_path, cache_dir)
            second = load_schema_document(schema_path, cache_dir=cache_dir)

            self.assertTrue(cache_path.exists())
            self.assertEqual(first.domains, second.domains)
            self.assertEqual(first.modules, second.modules)
            self.assertEqual(second.domains[0].key, "product")


if __name__ == "__main__":
    unittest.main()
