import email
import email.policy
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from terminology_import import snowstorm


class FakeSnowstorm:
    """A real HTTP server on localhost that records requests and answers with canned responses."""

    def __init__(self):
        self.requests = []
        self.responses = {}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.answer()

            def do_POST(self):
                self.answer()

            def answer(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                fake.requests.append({"method": self.command, "path": self.path,
                                      "content_type": self.headers.get("Content-Type"), "body": body})
                response = fake.responses.get(self.path.split("?")[0], (404, b"not found"))
                status, response_body = response() if callable(response) else response
                self.send_response(status)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def multipart_parts(request):
    """Parse a recorded multipart/form-data request into {field name: [bytes, ...]}."""
    message = email.message_from_bytes(
        b"Content-Type: " + request["content_type"].encode() + b"\r\n\r\n" + request["body"], policy=email.policy.HTTP)
    parts = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        parts.setdefault(name, []).append(part.get_payload(decode=True))
    return parts


class SnowstormTest(unittest.TestCase):

    def setUp(self):
        self.fake = FakeSnowstorm()
        self.addCleanup(self.fake.close)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.package_path = os.path.join(directory.name, "icd-10-is.tgz")
        with open(self.package_path, "wb") as file:
            file.write(b"\x1f\x8b package bytes \x00\xff")

    def test_load_package_uploads_the_file_and_asks_for_all_resources(self):
        self.fake.responses["/fhir-admin/load-package"] = (200, b"")

        snowstorm.load_package(self.fake.url, self.package_path)

        self.assertEqual(1, len(self.fake.requests))
        request = self.fake.requests[0]
        self.assertEqual(("POST", "/fhir-admin/load-package"), (request["method"], request["path"]))
        parts = multipart_parts(request)
        self.assertEqual([b"\x1f\x8b package bytes \x00\xff"], parts["file"])
        self.assertEqual([b"*"], parts["resourceUrls"])

    def test_load_package_accepts_a_base_url_with_a_trailing_slash(self):
        self.fake.responses["/fhir-admin/load-package"] = (200, b"")

        snowstorm.load_package(self.fake.url + "/", self.package_path)

        self.assertEqual("/fhir-admin/load-package", self.fake.requests[0]["path"])

    def test_load_package_reports_the_servers_error_message(self):
        self.fake.responses["/fhir-admin/load-package"] = (400, b'{"issue":[{"diagnostics":"File not found within package."}]}')

        with self.assertRaisesRegex(snowstorm.SnowstormError, "400.*File not found within package"):
            snowstorm.load_package(self.fake.url, self.package_path)

    def test_count_concepts_expands_the_implicit_value_set_of_the_code_system(self):
        self.fake.responses["/fhir/ValueSet/$expand"] = (200, json.dumps(
            {"resourceType": "ValueSet", "expansion": {"total": 14756, "contains": [{"code": "A00"}]}}).encode())

        total = snowstorm.count_concepts(self.fake.url, "http://landlaeknir.is/fhir/CodeSystem/icd-10-is")

        self.assertEqual(14756, total)
        self.assertEqual(
            "/fhir/ValueSet/$expand?url=http%3A%2F%2Flandlaeknir.is%2Ffhir%2FCodeSystem%2Ficd-10-is%3Ffhir_vs&count=1",
            self.fake.requests[0]["path"])

    def test_count_concepts_is_zero_when_the_code_system_is_not_loaded(self):
        self.fake.responses["/fhir/ValueSet/$expand"] = (400, json.dumps({"resourceType": "OperationOutcome", "issue": [
            {"severity": "error", "code": "not-found", "diagnostics": "Code system not found for parameters X."}]}).encode())

        self.assertEqual(0, snowstorm.count_concepts(self.fake.url, "http://landlaeknir.is/fhir/CodeSystem/icd-10-is"))

    def test_count_concepts_raises_on_other_server_errors(self):
        self.fake.responses["/fhir/ValueSet/$expand"] = (500, b"boom")

        with self.assertRaisesRegex(snowstorm.SnowstormError, "500"):
            snowstorm.count_concepts(self.fake.url, "http://landlaeknir.is/fhir/CodeSystem/icd-10-is")


if __name__ == "__main__":
    unittest.main()
