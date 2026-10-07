"""Harvests code systems from the legacy skafl.is site and turns them into FHIR CodeSystems.

The site exposes its tree as JSON: `Default.aspx?Command=GetCodeChildren&node=<id>` returns the
children of a node, and node 0 lists the code systems. A harvest walks one code system, waits
between requests, and saves progress to a file so an interrupted run resumes where it stopped.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

SITE = "https://skafl.is/Default.aspx"
URL_PREFIX = "http://landlaeknir.is/fhir/CodeSystem/"

# Resource ids that differ from the lower-cased site name; ICD-10 keeps the id other systems already query.
IDS = {"ICD-10": "icd-10-is"}

UNTRANSLATED = {"vantar þýðingu", "þýðingu vantar"}

# (site field, property code) for the extra texts the site shows beside a code.
TEXT_PROPERTIES = [("inclisl", "inclusion-is"), ("inclengl", "inclusion-en"),
                   ("exclisl", "exclusion-is"), ("exclengl", "exclusion-en"),
                   ("noteisl", "note-is"), ("noteengl", "note-en"),
                   ("textisl", "text-is"), ("textengl", "text-en")]

RETRIES = 3


class SkaflError(Exception):
    """The site could not be read, or a harvest is not usable."""


def list_systems(site=SITE):
    return _children(site, 0)


def harvest(system, path, site=SITE, sleep=None, delay=1.0, save_every=25):
    """Walk one code system into `path`. Re-running continues an unfinished harvest."""
    import time
    sleep = sleep or time.sleep

    if os.path.exists(path):
        with open(path, encoding="utf-8") as file:
            state = json.load(file)
    else:
        roots = list_systems(site)
        matches = [root for root in roots if root["name"] == system]
        if not matches:
            raise SkaflError("No code system named %s on %s; the site has: %s"
                             % (system, site, ", ".join(root["name"] for root in roots)))
        state = {"system": system, "root": matches[0], "pending": [matches[0]["id"]], "nodes": {}}

    since_save = 0
    while state["pending"]:
        sleep(delay)
        parent_id = state["pending"][0]
        for child in _children(site, parent_id):
            state["nodes"][str(child["id"])] = child
            if not child["leaf"]:
                state["pending"].append(child["id"])
        state["pending"].pop(0)
        since_save += 1
        if since_save >= save_every:
            _save(state, path)
            since_save = 0
    _save(state, path)
    return len(state["nodes"])


def build_code_system(harvested, version):
    if harvested["pending"]:
        raise SkaflError("The harvest of %s is not finished; %d nodes are still pending."
                         % (harvested["system"], len(harvested["pending"])))
    root = harvested["root"]
    nodes = harvested["nodes"]

    # Children in the order the site lists them (the harvest keeps that order), so the tree can be
    # shown in the same order; Snowstorm keeps supplied `child` properties as given.
    children = {}
    for node in nodes.values():
        children.setdefault(node["parentid"], []).append(node["name"].strip())

    concepts = []
    for node in [root] + list(nodes.values()):
        icelandic, english = node["phraseisl"].strip(), node["phraseengl"].strip()
        designations = []
        if icelandic and icelandic.lower() not in UNTRANSLATED:
            designations.append({"language": "is", "value": icelandic})
        if english:
            designations.append({"language": "en", "value": english})
        if not designations:
            raise SkaflError("Code %s in %s has no name in either language." % (node["name"], root["name"]))
        concept = {"code": node["name"].strip(), "display": designations[0]["value"], "designation": designations}

        properties = []
        if node is not root:
            parent = root if node["parentid"] == root["id"] else nodes[str(node["parentid"])]
            properties.append({"code": "parent", "valueCode": parent["name"].strip()})
        for field, code in TEXT_PROPERTIES:
            if node.get(field, "").strip():
                properties.append({"code": code, "valueString": node[field].strip()})
        for child in children.get(node["id"], []):
            properties.append({"code": "child", "valueCode": child})
        if properties:
            concept["property"] = properties
        concepts.append(concept)

    system_id = IDS.get(root["name"], root["name"].lower())
    return {
        "resourceType": "CodeSystem",
        "id": system_id,
        "url": URL_PREFIX + system_id,
        "version": version,
        "name": root["name"].replace("-", ""),
        "title": root["phraseengl"].strip() or root["name"],
        "status": "active",
        "publisher": "Embætti landlæknis",
        "caseSensitive": True,
        "hierarchyMeaning": "is-a",
        "content": "complete",
        "count": len(concepts),
        "property": [{"code": "parent", "uri": "http://hl7.org/fhir/concept-properties#parent", "type": "code"},
                     {"code": "child", "uri": "http://hl7.org/fhir/concept-properties#child", "type": "code"}]
                    + [{"code": code, "type": "string"} for _, code in TEXT_PROPERTIES],
        "concept": concepts,
    }


def merge_texts(code_system, details):
    """Complete the site's texts from a CSV export of the same database.

    The site cuts each text to its first line. For a code whose Icelandic name matches the export,
    an export text replaces the site's when the site's is empty or is the first line of it.
    `details` maps code -> list-file row (see icd10.TEXT_PROPERTIES for the columns).
    """
    from terminology_import import icd10
    for concept in code_system["concept"]:
        detail = details.get(concept["code"])
        if not detail or detail.get("PHRASE_ISL", "").strip() != concept["display"]:
            continue
        properties = concept.setdefault("property", [])
        by_code = {p["code"]: p for p in properties}
        for column, property_code in icd10.TEXT_PROPERTIES:
            full = detail.get(column, "").strip()
            if not full:
                continue
            current = by_code.get(property_code)
            if current is None:
                properties.append({"code": property_code, "valueString": full})
            elif full.splitlines()[0].strip() == current["valueString"].strip():
                current["valueString"] = full
        if not properties:
            del concept["property"]


def _children(site, node_id):
    url = site + "?" + urllib.parse.urlencode({"Command": "GetCodeChildren", "node": node_id})
    last_error = None
    for _ in range(RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError) as error:
            last_error = error
    raise SkaflError("GET %s failed %d times: %s" % (url, RETRIES, last_error))


def _save(state, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + ".part"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)
    os.replace(temporary, path)
