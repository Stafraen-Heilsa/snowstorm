# terminology-import

Builds terminology packages from source files and loads them into Snowstorm.
Plain Python 3.9+, no packages to install.

Snowstorm has no `POST /fhir/CodeSystem`. Code systems other than SNOMED CT go in as a FHIR package
(`.tgz`) through `/fhir-admin/load-package`, so that is what this tool produces and uploads.

## What is in this folder

| Path | Contents |
|---|---|
| `sources/skafl/*.json` | The six code systems as harvested from skafl.is on 2026-10-07 (one request per parent node; the site's text fields are cut to their first line) |
| `sources/icd10/` | Landlæknir's ICD-10 CSV export pair (`;`-separated, Windows-1252); its texts are complete |
| `packages/*.tgz` | The FHIR packages built from the above and loaded into Snowstorm (version 2026-10-07) |
| `out/` | Working directory for new builds (not in git) |

Every code system gets a root concept whose code is the system's name (`ICD-10`, `NCSP`, …) with the
chapters as its children, `child` properties in the order the site shows them, Icelandic as the display
with Icelandic and English designations, and the inclusion/exclusion/note/text fields as string properties
(`inclusion-is`, `exclusion-en`, …). A code whose Icelandic name is the placeholder "Vantar þýðingu" gets
the English name as display.

## Loading the packages

```sh
cd terminology-import
python -m terminology_import load --to http://localhost:8080 packages/*.tgz
```

The command uploads each package and checks that Snowstorm holds as many concepts as the package.
Loading a package again replaces the previous content of that code system.

## Harvesting from skafl.is

```sh
# One code system; re-running continues an interrupted harvest from where it stopped
python -m terminology_import skafl --system NCSP --version 2026-10-07 --out-dir out/skafl --delay 1.0

# ICD-10 with the full texts taken from the CSV export where the site's first line matches
python -m terminology_import skafl --system ICD-10 --version 2026-10-07 --out-dir out/skafl \
  --texts-from sources/icd10/ICD10_listi.csv

# What the site offers
python -m terminology_import skafl --list
```

## Icelandic ICD-10 from the CSV export alone

Source: the CSV pair Landlæknir publishes, `ICD10_tré.csv` and `ICD10_listi.csv`
(`;`-separated, Windows-1252). Note that the January 2025 export is older than the live site
(the site has since added e.g. K90.0A and retired the F64 group), so the harvested ICD-10 is the one loaded.

```sh
cd terminology-import

# Build the package only
python -m terminology_import icd10 \
  --tree path/to/ICD10_tré.csv --list path/to/ICD10_listi.csv \
  --version 2025-01-31 --out out/icd-10-is.tgz

# Build it and load it into a Snowstorm
python -m terminology_import icd10 \
  --tree path/to/ICD10_tré.csv --list path/to/ICD10_listi.csv \
  --version 2025-01-31 --out out/icd-10-is.tgz --load http://localhost:8080
```

`--version` is the date of the export. With `--load` the command uploads the package, then asks
Snowstorm how many concepts it holds for the code system and fails if that differs from the package.

What ends up in Snowstorm:

| | |
|---|---|
| URL | `http://landlaeknir.is/fhir/CodeSystem/icd-10-is` |
| Id | `icd-10-is` (always the same, so a new export replaces the previous one) |
| Codes | every row of the tree file, exactly as written there |
| Display | the Icelandic name; Icelandic and English are both designations |
| Hierarchy | `parent` from the tree file's `RELATED_CODE` |
| Retired codes | `STATUS` other than `1` in the list file becomes `inactive = true` |

The build stops with an error if a code appears twice, has no Icelandic name, or points at a parent
that is not in the file.

### Known limits (Snowstorm 10.5.1)

- Snowstorm treats every non-SNOMED code as active. The `inactive` flag is in the package but
  search and validation do not act on it.
- `ValueSet/$expand` with `filter` matches the start of one word in the Icelandic display name,
  ignoring case (`kól` finds `Kólera`). It finds nothing for two or more words, for a code (`J45`),
  for an English name, or when accents are left out (`rikjandi`).

## Tests

```sh
cd terminology-import
python -m unittest discover -s tests -t .
```
