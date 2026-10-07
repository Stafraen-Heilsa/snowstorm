import tempfile
import unittest

from terminology_import import icd10
from tests import fixtures


class Icd10CodeSystemTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def build(self, tree_rows=None, list_rows=None):
        tree_path, list_path = fixtures.write_pair(self.directory.name, tree_rows, list_rows)
        return icd10.build_code_system(tree_path, list_path, version="2025-01-31")

    def concept(self, code_system, code):
        matches = [concept for concept in code_system["concept"] if concept["code"] == code]
        self.assertEqual(1, len(matches), "concepts with code %s" % code)
        return matches[0]

    def test_every_tree_row_becomes_a_concept_even_when_missing_from_the_list_file(self):
        code_system = self.build()

        self.assertEqual(["ICD-10", "I (A00-B99)", "(A00-A09)", "A00", "A00.0", "A00.1", "A90"],
                         [concept["code"] for concept in code_system["concept"]])
        self.assertEqual(7, code_system["count"])

    def test_icelandic_name_is_the_display_and_both_languages_are_designations(self):
        concept = self.concept(self.build(), "(A00-A09)")

        self.assertEqual("Smitsjúkdómar í görnum", concept["display"])
        self.assertEqual([{"language": "is", "value": "Smitsjúkdómar í görnum"},
                          {"language": "en", "value": "Intestinal infectious diseases"}],
                         concept["designation"])

    def test_parent_is_taken_from_the_related_code(self):
        code_system = self.build()

        self.assertIn({"code": "parent", "valueCode": "A00"}, self.concept(code_system, "A00.0")["property"])
        self.assertEqual([{"code": "parent", "valueCode": "(A00-A09)"}], self.concept(code_system, "A90")["property"])

    def test_the_classification_itself_is_the_root_and_chapters_hang_under_it(self):
        code_system = self.build()

        root = self.concept(code_system, "ICD-10")
        self.assertEqual("Alþjóðleg tölfræðiflokkun sjúkdóma", root["display"])
        self.assertNotIn("property", root)
        self.assertEqual([{"code": "parent", "valueCode": "ICD-10"}], self.concept(code_system, "I (A00-B99)")["property"])

    def test_windows_1252_characters_such_as_dagger_and_bullet_are_decoded(self):
        self.assertIn({"code": "exclusion-is", "valueString": "Útilokar:\n• kóleru† (A00.9)"},
                      self.concept(self.build(), "A00")["property"])

    def test_code_with_status_other_than_1_is_flagged_inactive(self):
        code_system = self.build()

        self.assertIn({"code": "inactive", "valueBoolean": True}, self.concept(code_system, "A00.1")["property"])
        self.assertNotIn({"code": "inactive", "valueBoolean": True}, self.concept(code_system, "A00.0")["property"])

    def test_inclusions_exclusions_notes_texts_and_definitions_come_from_the_list_file(self):
        code_system = self.build()

        a00 = self.concept(code_system, "A00")["property"]
        self.assertIn({"code": "inclusion-is", "valueString": "Innifalið: kólera"}, a00)
        self.assertIn({"code": "exclusion-en", "valueString": "Excl.: not cholera"}, a00)
        self.assertIn({"code": "note-en", "valueString": "Note for A00"}, a00)
        self.assertIn({"code": "definition-is", "valueString": "Skilgreining"}, a00)
        self.assertIn({"code": "text-is", "valueString": "Hefðbundin\nkólera"},
                      self.concept(code_system, "A00.0")["property"])
        self.assertEqual(["parent"], [p["code"] for p in self.concept(code_system, "A90")["property"]])

    def test_code_system_is_published_under_the_url_snjokorn_queries(self):
        code_system = self.build()

        self.assertEqual("CodeSystem", code_system["resourceType"])
        self.assertEqual("http://landlaeknir.is/fhir/CodeSystem/icd-10-is", code_system["url"])
        self.assertEqual("icd-10-is", code_system["id"])
        self.assertEqual("2025-01-31", code_system["version"])
        # Snowstorm skips the concepts of a 'not-present' code system and only builds the hierarchy for 'is-a'.
        self.assertEqual("complete", code_system["content"])
        self.assertEqual("is-a", code_system["hierarchyMeaning"])

    def test_missing_icelandic_name_is_rejected(self):
        rows = list(fixtures.TREE_ROWS)
        rows[2] = "6;10;4;3;A00;;Cholera;P;1;1;1;Smitsjúkdómar í görnum;Intestinal infectious diseases;(A00-A09);A00"

        with self.assertRaisesRegex(icd10.SourceError, "A00.*PHRASE_ISL"):
            self.build(tree_rows=rows)

    def test_parent_that_is_not_in_the_file_is_rejected(self):
        rows = [row for row in fixtures.TREE_ROWS if not row.startswith("6;")]  # drop A00, the parent of A00.0

        with self.assertRaisesRegex(icd10.SourceError, "A00.0.*A00"):
            self.build(tree_rows=rows)

    def test_duplicate_code_is_rejected(self):
        with self.assertRaisesRegex(icd10.SourceError, "A90.*more than once"):
            self.build(tree_rows=fixtures.TREE_ROWS + [fixtures.TREE_ROWS[-1]])


if __name__ == "__main__":
    unittest.main()
