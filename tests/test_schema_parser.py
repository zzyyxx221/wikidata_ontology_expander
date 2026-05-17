import unittest

from wikidata_ontology_expander.schema_parser import parse_schema_text


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


if __name__ == "__main__":
    unittest.main()

