import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from terminology_import import skafl


def node(id, parentid, name, isl, engl, leaf, **extra):
    record = {"id": id, "parentid": parentid, "leaf": leaf, "text": "%s %s" % (name, isl), "name": name,
              "codingsystem": "NCSP", "phraseisl": isl, "phraseengl": engl, "exclisl": "", "exclengl": "",
              "xexcl": "", "inclisl": "", "inclengl": "", "xincl": "", "noteisl": "", "noteengl": "", "xnote": "",
              "textisl": "", "textengl": "", "xtext": "", "icon": "resources/images/default/tree/leaf.gif"}
    record.update(extra)
    return record


# The site's tree: two code systems at the root; NCSP has a chapter with two codes, one of them a leaf.
ROOTS = [node(1, 0, "ICD-10", "Alþjóðleg tölfræðiflokkun", "International Classification of Diseases", False,
              codingsystem="ICD-10"),
         node(100001, 0, "NCSP", "Norræn flokkun aðgerða", "NOMESCO Classification of Surgical Procedures", False)]
CHILDREN = {
    "0": ROOTS,
    "100001": [node(100002, 100001, "A", "Kafli A - Taugakerfið", "Chapter A - Nervous system", False,
                    inclisl="Innifalið: taugar", exclengl="Excl.: eyes")],
    "100002": [node(100003, 100002, "AA", "Höfuðkúpa", "Skull", False, noteisl="Athugið: höfuð"),
               node(100004, 100002, "AAA00", "Opnun höfuðkúpu", "Craniotomy", True, textengl="free text")],
    "100003": [node(100005, 100003, "AAB00", "Aðgerð á höfuðkúpu", "Skull operation", True)],
}


def read_json(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


class FakeSkafl:
    def __init__(self, children):
        self.requests = []
        self.fail_next = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlparse(self.path).query)
                fake.requests.append(self.path)
                if fake.fail_next:
                    fake.fail_next -= 1
                    self.send_response(500)
                    self.end_headers()
                    return
                body = json.dumps(children.get(query["node"][0], [])).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/Default.aspx" % self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class HarvestTest(unittest.TestCase):

    def setUp(self):
        self.fake = FakeSkafl(CHILDREN)
        self.addCleanup(self.fake.close)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "NCSP.json")
        self.sleeps = []

    def harvest(self, **kwargs):
        return skafl.harvest("NCSP", self.path, site=self.fake.url, sleep=self.sleeps.append, **kwargs)

    def test_lists_the_code_systems_at_the_root(self):
        systems = skafl.list_systems(site=self.fake.url)

        self.assertEqual([("ICD-10", 1), ("NCSP", 100001)], [(s["name"], s["id"]) for s in systems])

    def test_harvests_every_node_under_the_code_system_with_its_parent(self):
        self.harvest()

        data = read_json(self.path)
        self.assertEqual({"100002": 100001, "100003": 100002, "100004": 100002, "100005": 100003},
                         {id: n["parentid"] for id, n in data["nodes"].items()})
        self.assertEqual("NCSP", data["root"]["name"])
        self.assertEqual([], data["pending"])

    def test_does_not_ask_for_the_children_of_a_leaf(self):
        self.harvest()

        asked = [parse_qs(urlparse(p).query)["node"][0] for p in self.fake.requests]
        self.assertEqual(["0", "100001", "100002", "100003"], asked)

    def test_waits_between_requests(self):
        self.harvest(delay=0.5)

        self.assertEqual([0.5, 0.5, 0.5], self.sleeps)

    def test_resumes_from_a_saved_file_without_refetching(self):
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump({"system": "NCSP", "root": ROOTS[1], "pending": [100003],
                       "nodes": {"100002": CHILDREN["100001"][0], "100003": CHILDREN["100002"][0],
                                 "100004": CHILDREN["100002"][1]}}, file)

        self.harvest()

        asked = [parse_qs(urlparse(p).query)["node"][0] for p in self.fake.requests]
        self.assertEqual(["100003"], asked)
        self.assertEqual(4, len(read_json(self.path)["nodes"]))

    def test_saves_progress_so_an_interrupted_run_can_resume(self):
        def sleep_then_die(seconds):
            self.sleeps.append(seconds)
            if len(self.sleeps) == 2:
                raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            skafl.harvest("NCSP", self.path, site=self.fake.url, sleep=sleep_then_die, save_every=1)

        data = read_json(self.path)
        self.assertEqual(["100002"], list(data["nodes"]))
        self.assertEqual([100002], data["pending"])

    def test_retries_a_failed_request_before_giving_up(self):
        self.fake.fail_next = 1

        self.harvest()

        self.assertEqual(4, len(read_json(self.path)["nodes"]))

    def test_unknown_code_system_is_an_error(self):
        with self.assertRaisesRegex(skafl.SkaflError, "NOPE.*ICD-10, NCSP"):
            skafl.harvest("NOPE", self.path, site=self.fake.url, sleep=self.sleeps.append)


class BuildCodeSystemTest(unittest.TestCase):

    def setUp(self):
        self.harvested = {"system": "NCSP", "root": ROOTS[1], "pending": [],
                          "nodes": {str(n["id"]): n for group in ("100001", "100002", "100003") for n in CHILDREN[group]}}

    def build(self, harvested=None):
        return skafl.build_code_system(harvested or self.harvested, version="2026-10-07")

    def concept(self, code):
        return [c for c in self.build()["concept"] if c["code"] == code][0]

    def test_code_system_is_identified_by_the_system_name(self):
        code_system = self.build()

        self.assertEqual("http://landlaeknir.is/fhir/CodeSystem/ncsp", code_system["url"])
        self.assertEqual("ncsp", code_system["id"])
        self.assertEqual("2026-10-07", code_system["version"])
        self.assertEqual("NOMESCO Classification of Surgical Procedures", code_system["title"])
        self.assertEqual("complete", code_system["content"])
        self.assertEqual(5, code_system["count"])

    def test_icd_10_keeps_the_id_and_url_snjokorn_already_uses(self):
        harvested = dict(self.harvested, system="ICD-10", root=dict(ROOTS[1], name="ICD-10"))

        code_system = self.build(harvested)

        self.assertEqual("icd-10-is", code_system["id"])
        self.assertEqual("http://landlaeknir.is/fhir/CodeSystem/icd-10-is", code_system["url"])

    def test_hyphenated_system_name_keeps_its_hyphen_in_the_id(self):
        harvested = dict(self.harvested, system="NCSP-IS", root=dict(ROOTS[1], name="NCSP-IS"))

        self.assertEqual("http://landlaeknir.is/fhir/CodeSystem/ncsp-is", self.build(harvested)["url"])

    def test_the_code_system_itself_is_the_root_concept_and_chapters_hang_under_it(self):
        root = self.concept("NCSP")

        self.assertEqual("Norræn flokkun aðgerða", root["display"])
        self.assertNotIn("parent", [p["code"] for p in root["property"]])
        self.assertEqual({"code": "parent", "valueCode": "NCSP"}, self.concept("A")["property"][0])
        self.assertEqual({"code": "parent", "valueCode": "A"}, self.concept("AA")["property"][0])

    def test_children_are_listed_on_each_parent_in_the_order_the_site_shows_them(self):
        code_system = self.build()

        root_children = [p["valueCode"] for p in self.concept("NCSP")["property"] if p["code"] == "child"]
        self.assertEqual(["A"], root_children)
        a_children = [p["valueCode"] for p in self.concept("A")["property"] if p["code"] == "child"]
        self.assertEqual(["AA", "AAA00"], a_children)
        self.assertNotIn("child", [p["code"] for p in self.concept("AAB00")["property"]])

    def test_icelandic_is_display_and_english_a_designation(self):
        concept = self.concept("AAA00")

        self.assertEqual("Opnun höfuðkúpu", concept["display"])
        self.assertEqual([{"language": "is", "value": "Opnun höfuðkúpu"}, {"language": "en", "value": "Craniotomy"}],
                         concept["designation"])

    def test_inclusions_exclusions_notes_and_text_become_properties_per_language(self):
        self.assertIn({"code": "inclusion-is", "valueString": "Innifalið: taugar"}, self.concept("A")["property"])
        self.assertIn({"code": "exclusion-en", "valueString": "Excl.: eyes"}, self.concept("A")["property"])
        self.assertIn({"code": "note-is", "valueString": "Athugið: höfuð"}, self.concept("AA")["property"])
        self.assertIn({"code": "text-en", "valueString": "free text"}, self.concept("AAA00")["property"])
        self.assertEqual(["parent"], [p["code"] for p in self.concept("AAB00")["property"]])

    def test_untranslated_placeholder_falls_back_to_english_display(self):
        self.harvested["nodes"]["100004"] = dict(CHILDREN["100002"][1], phraseisl="Vantar þýðingu")

        concept = self.concept("AAA00")

        self.assertEqual("Craniotomy", concept["display"])
        self.assertEqual([{"language": "en", "value": "Craniotomy"}], concept["designation"])

    def test_incomplete_harvest_is_rejected(self):
        self.harvested["pending"] = [100003]

        with self.assertRaisesRegex(skafl.SkaflError, "not finished"):
            self.build()


class MergeTextsTest(unittest.TestCase):
    """The site cuts texts to their first line; the CSV export of the same database has them in full."""

    def setUp(self):
        self.code_system = {"concept": [
            {"code": "A", "display": "Kafli A - Taugakerfið", "property": [
                {"code": "inclusion-is", "valueString": "Innifalið: taugar"},
                {"code": "exclusion-en", "valueString": "Excl.: eyes"}]},
            {"code": "AA", "display": "Höfuðkúpa", "property": [{"code": "parent", "valueCode": "A"}]},
            {"code": "U52.9", "display": "Einhverfurófsröskun", "property": [
                {"code": "note-is", "valueString": "Gamla athugasemdin"}]},
        ]}
        self.details = {
            "A": {"PHRASE_ISL": "Kafli A - Taugakerfið", "INCL_ISL": "Innifalið: taugar\n• og fleira",
                  "EXCL_ENGL": "Something else entirely", "NOTE_ISL": "Ný athugasemd"},
            "AA": {"PHRASE_ISL": "Höfuðkúpa", "TEXT_ENGL": "Skull text"},
            "U52.9": {"PHRASE_ISL": "Neyðarnotkun landskóða", "NOTE_ISL": "Gamla athugasemdin\nframhald"},
        }

    def props(self, code):
        return {p["code"]: p.get("valueString", p.get("valueCode"))
                for c in self.code_system["concept"] if c["code"] == code for p in c["property"]}

    def test_full_text_replaces_a_truncated_first_line(self):
        skafl.merge_texts(self.code_system, self.details)

        self.assertEqual("Innifalið: taugar\n• og fleira", self.props("A")["inclusion-is"])

    def test_text_that_does_not_start_with_the_sites_line_is_kept_from_the_site(self):
        skafl.merge_texts(self.code_system, self.details)

        self.assertEqual("Excl.: eyes", self.props("A")["exclusion-en"])

    def test_text_missing_on_the_site_is_added_from_the_export(self):
        skafl.merge_texts(self.code_system, self.details)

        self.assertEqual("Ný athugasemd", self.props("A")["note-is"])
        self.assertEqual("Skull text", self.props("AA")["text-en"])

    def test_export_is_ignored_when_the_code_has_been_given_a_different_name(self):
        skafl.merge_texts(self.code_system, self.details)

        self.assertEqual("Gamla athugasemdin", self.props("U52.9")["note-is"])


if __name__ == "__main__":
    unittest.main()