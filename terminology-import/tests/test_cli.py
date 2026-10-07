import contextlib
import io
import json
import os
import tarfile
import tempfile
import unittest

from terminology_import import cli
from tests import fixtures
from tests.test_snowstorm import FakeSnowstorm


class Icd10CommandTest(unittest.TestCase):

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tree_path, self.list_path = fixtures.write_pair(directory.name)
        self.out_path = os.path.join(directory.name, "icd-10-is.tgz")
        self.args = ["icd10", "--tree", self.tree_path, "--list", self.list_path,
                     "--version", "2025-01-31", "--out", self.out_path]

    def run_cli(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exit_code = cli.main(args)
        return exit_code, output.getvalue()

    def test_builds_a_package_holding_the_code_system(self):
        exit_code, output = self.run_cli(self.args)

        self.assertEqual(0, exit_code, output)
        with tarfile.open(self.out_path, "r:gz") as archive:
            code_system = json.loads(archive.extractfile("package/CodeSystem-icd-10-is.json").read().decode("utf-8"))
        self.assertEqual("2025-01-31", code_system["version"])
        self.assertEqual(7, len(code_system["concept"]))

    def test_load_uploads_the_package_and_confirms_the_concept_count(self):
        fake = FakeSnowstorm()
        self.addCleanup(fake.close)
        fake.responses["/fhir-admin/load-package"] = (200, b"")
        fake.responses["/fhir/ValueSet/$expand"] = (200, json.dumps({"expansion": {"total": 7}}).encode())

        exit_code, output = self.run_cli(self.args + ["--load", fake.url])

        self.assertEqual(0, exit_code, output)
        self.assertEqual(["/fhir-admin/load-package", "/fhir/ValueSet/$expand"],
                         [request["path"].split("?")[0] for request in fake.requests])

    def test_load_fails_when_the_server_holds_a_different_number_of_concepts(self):
        fake = FakeSnowstorm()
        self.addCleanup(fake.close)
        fake.responses["/fhir-admin/load-package"] = (200, b"")
        fake.responses["/fhir/ValueSet/$expand"] = (200, json.dumps({"expansion": {"total": 4}}).encode())

        exit_code, output = self.run_cli(self.args + ["--load", fake.url])

        self.assertEqual(1, exit_code)
        self.assertRegex(output, "expected 7.*found 4")

    def test_bad_source_file_is_reported_without_writing_a_package(self):
        tree_path, list_path = fixtures.write_pair(os.path.dirname(self.tree_path),
                                                   tree_rows=fixtures.TREE_ROWS + [fixtures.TREE_ROWS[-1]])

        exit_code, output = self.run_cli(self.args)

        self.assertEqual(1, exit_code)
        self.assertRegex(output, "A90.*more than once")
        self.assertFalse(os.path.exists(self.out_path))


class SkaflCommandTest(unittest.TestCase):

    def setUp(self):
        from tests.test_skafl import CHILDREN, FakeSkafl
        self.site = FakeSkafl(CHILDREN)
        self.addCleanup(self.site.close)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.out_dir = os.path.join(directory.name, "skafl")

    def run_cli(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exit_code = cli.main(args)
        return exit_code, output.getvalue()

    def test_harvests_one_code_system_and_builds_its_package(self):
        exit_code, output = self.run_cli(["skafl", "--system", "NCSP", "--site", self.site.url, "--delay", "0",
                                          "--version", "2026-10-07", "--out-dir", self.out_dir])

        self.assertEqual(0, exit_code, output)
        with tarfile.open(os.path.join(self.out_dir, "ncsp.tgz"), "r:gz") as archive:
            code_system = json.loads(archive.extractfile("package/CodeSystem-ncsp.json").read().decode("utf-8"))
        self.assertEqual(5, len(code_system["concept"]))
        self.assertTrue(os.path.exists(os.path.join(self.out_dir, "NCSP.json")))

    def test_texts_from_completes_the_harvest_with_the_export_file(self):
        list_path = os.path.join(os.path.dirname(self.out_dir), "ICD10_listi.csv")
        with open(list_path, "w", encoding="cp1252", newline="") as file:
            file.write(fixtures.LIST_HEADER + "\r\n" + fixtures._list_row(
                "9", "A", "Kafli A - Taugakerfið", "Chapter A - Nervous system", "H",
                INCL_ISL="Innifalið: taugar\n• og fleira") + "\r\n")

        exit_code, output = self.run_cli(["skafl", "--system", "NCSP", "--site", self.site.url, "--delay", "0",
                                          "--version", "2026-10-07", "--out-dir", self.out_dir,
                                          "--texts-from", list_path])

        self.assertEqual(0, exit_code, output)
        with tarfile.open(os.path.join(self.out_dir, "ncsp.tgz"), "r:gz") as archive:
            code_system = json.loads(archive.extractfile("package/CodeSystem-ncsp.json").read().decode("utf-8"))
        chapter = [c for c in code_system["concept"] if c["code"] == "A"][0]
        self.assertIn({"code": "inclusion-is", "valueString": "Innifalið: taugar\n• og fleira"}, chapter["property"])

    def test_list_prints_the_code_systems_on_the_site(self):
        exit_code, output = self.run_cli(["skafl", "--list", "--site", self.site.url])

        self.assertEqual(0, exit_code, output)
        self.assertIn("NCSP", output)
        self.assertIn("ICD-10", output)


class LoadCommandTest(unittest.TestCase):

    def setUp(self):
        from terminology_import import fhir_package
        self.fake = FakeSnowstorm()
        self.addCleanup(self.fake.close)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.packages = []
        for system_id, count in (("hjgr", 2), ("icf", 3)):
            path = os.path.join(directory.name, system_id + ".tgz")
            fhir_package.write(path, name="x", version="1", resources=[{
                "resourceType": "CodeSystem", "id": system_id, "version": "1",
                "url": "http://landlaeknir.is/fhir/CodeSystem/" + system_id,
                "concept": [{"code": "c%d" % i, "display": "d"} for i in range(count)]}])
            self.packages.append(path)

    def run_cli(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            exit_code = cli.main(args)
        return exit_code, output.getvalue()

    def test_uploads_each_package_and_checks_its_concept_count(self):
        self.fake.responses["/fhir-admin/load-package"] = (200, b"")
        totals = iter([2, 3])
        self.fake.responses["/fhir/ValueSet/$expand"] = lambda: (
            200, json.dumps({"expansion": {"total": next(totals)}}).encode())

        exit_code, output = self.run_cli(["load", "--to", self.fake.url] + self.packages)

        self.assertEqual(0, exit_code, output)
        self.assertEqual(["/fhir-admin/load-package", "/fhir/ValueSet/$expand"] * 2,
                         [request["path"].split("?")[0] for request in self.fake.requests])

    def test_stops_at_the_first_package_whose_count_is_wrong(self):
        self.fake.responses["/fhir-admin/load-package"] = (200, b"")
        self.fake.responses["/fhir/ValueSet/$expand"] = (200, json.dumps({"expansion": {"total": 99}}).encode())

        exit_code, output = self.run_cli(["load", "--to", self.fake.url] + self.packages)

        self.assertEqual(1, exit_code)
        self.assertRegex(output, "expected 2.*found 99")
        self.assertEqual(2, len(self.fake.requests))


if __name__ == "__main__":
    unittest.main()
