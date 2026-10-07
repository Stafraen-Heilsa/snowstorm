"""The two Snowstorm calls the import needs: upload a FHIR package, and count what is loaded."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

# Snowstorm indexes the whole package before it answers.
LOAD_TIMEOUT_SECONDS = 1800
QUERY_TIMEOUT_SECONDS = 60


class SnowstormError(Exception):
    """Snowstorm rejected a request or could not be reached."""


def load_package(base_url, package_path):
    """Upload a FHIR package and import every CodeSystem and ValueSet in it."""
    with open(package_path, "rb") as file:
        package = file.read()
    boundary = uuid.uuid4().hex
    body = b"".join([
        _part_header(boundary, 'name="resourceUrls"'), b"*\r\n",
        _part_header(boundary, 'name="file"; filename="%s"' % os.path.basename(package_path),
                     "application/gzip"), package, b"\r\n",
        ("--%s--\r\n" % boundary).encode(),
    ])
    request = urllib.request.Request(_url(base_url, "fhir-admin/load-package"), data=body, method="POST",
                                     headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    _send(request, LOAD_TIMEOUT_SECONDS)


def count_concepts(base_url, code_system_url):
    """Number of concepts Snowstorm holds for a code system; 0 if the code system is not loaded."""
    query = urllib.parse.urlencode({"url": code_system_url + "?fhir_vs", "count": 1})
    request = urllib.request.Request(_url(base_url, "fhir/ValueSet/$expand?" + query))
    try:
        response = _send(request, QUERY_TIMEOUT_SECONDS)
    except SnowstormError as error:
        if "Code system not found" in str(error):
            return 0
        raise
    return json.loads(response)["expansion"]["total"]


def _url(base_url, path):
    return base_url.rstrip("/") + "/" + path


def _part_header(boundary, disposition, content_type=None):
    header = "--%s\r\nContent-Disposition: form-data; %s\r\n" % (boundary, disposition)
    if content_type:
        header += "Content-Type: %s\r\n" % content_type
    return (header + "\r\n").encode()


def _send(request, timeout):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SnowstormError("%s %s answered %d: %s" % (request.get_method(), request.full_url, error.code, detail))
    except OSError as error:
        raise SnowstormError("%s %s failed: %s" % (request.get_method(), request.full_url, error))
