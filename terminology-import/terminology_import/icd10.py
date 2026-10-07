"""Builds the Icelandic ICD-10 FHIR CodeSystem from Landlæknir's CSV export pair.

The tree file (ICD10_tré.csv) holds every code with its names and parent.
The list file (ICD10_listi.csv) holds the status and the texts of each code, plus one row for the
classification itself (TYPE "R"), which becomes the root concept.
Both are `;`-separated and Windows-1252 encoded.
"""
import csv

URL = "http://landlaeknir.is/fhir/CodeSystem/icd-10-is"
ID = "icd-10-is"

ACTIVE_STATUS = "1"
ROOT_TYPE = "R"
ROOT_CODE = "ICD-10"

# (list-file column, property code) for the texts shown beside a code.
TEXT_PROPERTIES = [("INCL_ISL", "inclusion-is"), ("INCL_ENGL", "inclusion-en"),
                   ("EXCL_ISL", "exclusion-is"), ("EXCL_ENGL", "exclusion-en"),
                   ("NOTE_ISL", "note-is"), ("NOTE_ENGL", "note-en"),
                   ("TEXT_ISL", "text-is"), ("TEXT_ENGL", "text-en"),
                   ("DEFINITION_ISL", "definition-is"), ("DEFINITION_ENGL", "definition-en"),
                   ("CONSIDER_ISL", "consider-is"), ("CONSIDER_ENGL", "consider-en")]


class SourceError(Exception):
    """The export files cannot be turned into a valid code system."""


def build_code_system(tree_path, list_path, version):
    details = read_details(list_path)
    root = details.get(ROOT_CODE, {})
    if root.get("TYPE") != ROOT_TYPE or not root.get("PHRASE_ISL"):
        raise SourceError("No root row (CODE %s, TYPE %s) with a PHRASE_ISL in %s." % (ROOT_CODE, ROOT_TYPE, list_path))

    concepts = [{"code": ROOT_CODE, "display": root["PHRASE_ISL"],
                 "designation": [{"language": "is", "value": root["PHRASE_ISL"]}]
                 + ([{"language": "en", "value": root["PHRASE_ENGL"]}] if root.get("PHRASE_ENGL") else [])}]
    parents = {}
    for row in _read(tree_path):
        code = row["CODE"]
        if code in parents:
            raise SourceError("Code %s is in %s more than once." % (code, tree_path))
        if not row["PHRASE_ISL"]:
            raise SourceError("Code %s has no PHRASE_ISL in %s." % (code, tree_path))
        parents[code] = row["RELATED_CODE"]

        concept = {"code": code, "display": row["PHRASE_ISL"],
                   "designation": [{"language": "is", "value": row["PHRASE_ISL"]}]}
        if row["PHRASE_ENGL"]:
            concept["designation"].append({"language": "en", "value": row["PHRASE_ENGL"]})
        properties = [{"code": "parent", "valueCode": row["RELATED_CODE"] or ROOT_CODE}]
        detail = details.get(code, {})
        if detail.get("STATUS", ACTIVE_STATUS) != ACTIVE_STATUS:
            properties.append({"code": "inactive", "valueBoolean": True})
        for column, property_code in TEXT_PROPERTIES:
            if detail.get(column):
                properties.append({"code": property_code, "valueString": detail[column]})
        if properties:
            concept["property"] = properties
        concepts.append(concept)

    for code, parent in parents.items():
        if parent and parent not in parents:
            raise SourceError("Code %s has parent %s, which is not in %s." % (code, parent, tree_path))

    return {
        "resourceType": "CodeSystem",
        "id": ID,
        "url": URL,
        "version": version,
        "name": "ICD10IS",
        "title": "ICD-10 (íslensk útgáfa)",
        "status": "active",
        "publisher": "Embætti landlæknis",
        "caseSensitive": True,
        "hierarchyMeaning": "is-a",
        "content": "complete",
        "count": len(concepts),
        "property": [
            {"code": "parent", "uri": "http://hl7.org/fhir/concept-properties#parent", "type": "code"},
            {"code": "inactive", "uri": "http://hl7.org/fhir/concept-properties#inactive", "type": "boolean"},
        ] + [{"code": property_code, "type": "string"} for _, property_code in TEXT_PROPERTIES],
        "concept": concepts,
    }


def read_details(list_path):
    """The list file's rows by code."""
    return {row["CODE"]: row for row in _read(list_path)}


def _read(path):
    with open(path, encoding="cp1252", newline="") as file:
        for row in csv.DictReader(file, delimiter=";"):
            yield {column: (value or "").strip() for column, value in row.items() if column is not None}
