import json
import os
import tarfile
import tempfile
import unittest

from terminology_import import fhir_package

CODE_SYSTEM = {
    "resourceType": "CodeSystem",
    "id": "icd-10-is",
    "url": "http://landlaeknir.is/fhir/CodeSystem/icd-10-is",
    "version": "2025-01-31",
    "concept": [{"code": "A00", "display": "Kólera"}],
}


class FhirPackageTest(unittest.TestCase):

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "nested", "icd-10-is.tgz")
        fhir_package.write(self.path, name="is.landlaeknir.icd-10-is", version="2025.1.31", resources=[CODE_SYSTEM])

    def read(self, member):
        with tarfile.open(self.path, "r:gz") as archive:
            return archive.extractfile(member).read()

    def test_index_lists_the_resource_so_snowstorm_can_find_it(self):
        index = json.loads(self.read("package/.index.json"))

        self.assertEqual([{"filename": "CodeSystem-icd-10-is.json",
                           "resourceType": "CodeSystem",
                           "id": "icd-10-is",
                           "url": "http://landlaeknir.is/fhir/CodeSystem/icd-10-is",
                           "version": "2025-01-31"}],
                         index["files"])

    def test_resource_is_stored_under_the_indexed_filename_as_utf8(self):
        raw = self.read("package/CodeSystem-icd-10-is.json")

        self.assertEqual(CODE_SYSTEM, json.loads(raw.decode("utf-8")))

    def test_package_manifest_names_the_package(self):
        manifest = json.loads(self.read("package/package.json"))

        self.assertEqual("is.landlaeknir.icd-10-is", manifest["name"])
        self.assertEqual("2025.1.31", manifest["version"])


if __name__ == "__main__":
    unittest.main()
