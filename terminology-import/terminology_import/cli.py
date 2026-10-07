import argparse
import sys

import json
import os

from terminology_import import fhir_package, icd10, skafl, snowstorm


def main(argv=None):
    parser = argparse.ArgumentParser(prog="terminology_import",
                                     description="Build terminology packages and load them into Snowstorm.")
    commands = parser.add_subparsers(dest="command", required=True)

    icd10_parser = commands.add_parser("icd10", help="Icelandic ICD-10 from Landlæknir's CSV export pair.")
    icd10_parser.add_argument("--tree", required=True, help="Path to ICD10_tré.csv.")
    icd10_parser.add_argument("--list", required=True, help="Path to ICD10_listi.csv.")
    icd10_parser.add_argument("--version", required=True, help="Date of the export, e.g. 2025-01-31.")
    icd10_parser.add_argument("--out", required=True, help="Package file to write, e.g. out/icd-10-is.tgz.")
    icd10_parser.add_argument("--load", metavar="SNOWSTORM_URL",
                              help="Also upload the package to this Snowstorm, replacing the loaded ICD-10.")
    icd10_parser.set_defaults(run=_icd10)

    skafl_parser = commands.add_parser("skafl", help="A code system harvested from the legacy skafl.is site.")
    skafl_parser.add_argument("--list", action="store_true", help="Only list the code systems on the site.")
    skafl_parser.add_argument("--system", help="Code system name as the site shows it, e.g. NCSP.")
    skafl_parser.add_argument("--version", help="Version to record, e.g. the harvest date 2026-10-07.")
    skafl_parser.add_argument("--out-dir", default="out/skafl",
                              help="Where the harvest (<SYSTEM>.json) and the package (<id>.tgz) go.")
    skafl_parser.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between requests.")
    skafl_parser.add_argument("--texts-from", metavar="LIST_CSV",
                              help="A list-file export of the same database (e.g. ICD10_listi.csv); its full "
                                   "inclusion, exclusion, note and text fields complete the site's first lines.")
    skafl_parser.add_argument("--site", default=skafl.SITE, help=argparse.SUPPRESS)
    skafl_parser.add_argument("--load", metavar="SNOWSTORM_URL",
                              help="Also upload the package to this Snowstorm, replacing the loaded code system.")
    skafl_parser.set_defaults(run=_skafl)

    load_parser = commands.add_parser("load", help="Upload already built packages to a Snowstorm.")
    load_parser.add_argument("packages", nargs="+", metavar="PACKAGE.tgz")
    load_parser.add_argument("--to", required=True, metavar="SNOWSTORM_URL")
    load_parser.set_defaults(run=_load)

    args = parser.parse_args(argv)
    try:
        args.run(args)
    except (icd10.SourceError, skafl.SkaflError, snowstorm.SnowstormError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    return 0


def _icd10(args):
    code_system = icd10.build_code_system(args.tree, args.list, args.version)
    _write_and_load(code_system, args.out, args.load)


def _skafl(args):
    if args.list:
        for root in skafl.list_systems(args.site):
            print("%-8s %s" % (root["name"], root["phraseengl"]))
        return
    if not args.system or not args.version:
        raise skafl.SkaflError("--system and --version are required unless --list is given.")

    harvest_path = os.path.join(args.out_dir, args.system + ".json")
    print("Harvesting %s from %s into %s (%.1fs between requests) ..." % (args.system, args.site, harvest_path, args.delay))
    nodes = skafl.harvest(args.system, harvest_path, site=args.site, delay=args.delay)
    print("Harvested %d nodes." % nodes)

    with open(harvest_path, encoding="utf-8") as file:
        code_system = skafl.build_code_system(json.load(file), args.version)
    if args.texts_from:
        skafl.merge_texts(code_system, icd10.read_details(args.texts_from))
    _write_and_load(code_system, os.path.join(args.out_dir, code_system["id"] + ".tgz"), args.load)


def _load(args):
    for package_path in args.packages:
        code_system = fhir_package.read_code_system(package_path)
        _load_package(package_path, code_system["url"], len(code_system["concept"]), args.to)


def _write_and_load(code_system, package_path, load_url):
    expected = len(code_system["concept"])
    fhir_package.write(package_path, name="is.landlaeknir." + code_system["id"], version=code_system["version"],
                       resources=[code_system])
    print("Wrote %s: %s version %s with %d concepts." % (package_path, code_system["url"], code_system["version"], expected))
    if load_url:
        _load_package(package_path, code_system["url"], expected, load_url)


def _load_package(package_path, url, expected, load_url):
    print("Loading %s into %s ..." % (package_path, load_url))
    snowstorm.load_package(load_url, package_path)
    found = snowstorm.count_concepts(load_url, url)
    if found != expected:
        raise snowstorm.SnowstormError(
            "expected %d concepts in %s after the load but found %d." % (expected, load_url, found))
    print("Loaded. %s holds %d concepts for %s." % (load_url, found, url))
