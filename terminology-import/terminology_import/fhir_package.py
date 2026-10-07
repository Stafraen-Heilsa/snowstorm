"""Writes FHIR resources as a FHIR package (.tgz), the format Snowstorm's /fhir-admin/load-package reads."""
import io
import json
import os
import tarfile


def read_code_system(path):
    """The single CodeSystem inside a package written by `write`."""
    with tarfile.open(path, "r:gz") as archive:
        index = json.loads(archive.extractfile("package/.index.json").read().decode("utf-8"))
        entry = [file for file in index["files"] if file["resourceType"] == "CodeSystem"][0]
        return json.loads(archive.extractfile("package/" + entry["filename"]).read().decode("utf-8"))


def write(path, name, version, resources):
    index_files = []
    members = {}
    for resource in resources:
        filename = "%s-%s.json" % (resource["resourceType"], resource["id"])
        index_files.append({"filename": filename, "resourceType": resource["resourceType"], "id": resource["id"],
                            "url": resource["url"], "version": resource["version"]})
        members[filename] = resource
    members[".index.json"] = {"index-version": 1, "files": index_files}
    members["package.json"] = {"name": name, "version": version, "fhirVersions": ["4.0.1"]}

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        for filename, content in members.items():
            data = json.dumps(content, ensure_ascii=False, indent=1).encode("utf-8")
            info = tarfile.TarInfo("package/" + filename)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
