"""A small CSV pair in the same shape as Landlæknir's ICD-10 export.

Like the real files: `;`-separated, Windows-1252, CRLF line endings. The tree file is unquoted,
the list file quotes every field and has line breaks inside fields.
"""
import os

TREE_HEADER = (
    "   Number;REL_GROUP_ID;INTERNAL_ID;RELATED_ID;CODE;PHRASE_ISL;PHRASE_ENGL;REL_TYPE;SIBLING_NO;"
    "ORDER_NO;HAS_FURTHER_REL;RELATED_PHRASE_ISL;RELATED_PHRASE_ENGL;RELATED_CODE;SEARCH_CODE"
)

TREE_ROWS = [
    "4;10;2;1;I (A00-B99);I. kafli - Tilteknir smit- og sníklasjúkdómar;Chapter I - Certain infectious and parasitic diseases;P;1;101;1;Alþjóðleg tölfræðiflokkun;International classification;;I(A00-B99)",
    "5;10;3;2;(A00-A09);Smitsjúkdómar í görnum;Intestinal infectious diseases;P;1;1;1;I. kafli;Chapter I;I (A00-B99);(A00-A09)",
    "6;10;4;3;A00;Kólera;Cholera;P;1;1;1;Smitsjúkdómar í görnum;Intestinal infectious diseases;(A00-A09);A00",
    "7;10;5;4;A00.0;Kólera af völdum Vibrio cholerae 01, biovar cholerae;Cholera due to Vibrio cholerae 01, biovar cholerae;P;1;1;0;Kólera;Cholera;A00;A000",
    "8;10;6;4;A00.1;Kólera af völdum Vibrio cholerae 01, biovar eltor;Cholera due to Vibrio cholerae 01, biovar eltor;P;2;2;0;Kólera;Cholera;A00;A001",
    # Present in the tree file only, and with a blank REL_TYPE, as happens in the real export.
    "9;10;7;3;A90;Beinbrunasótt;Dengue fever;;2;2;0;Smitsjúkdómar í görnum;Intestinal infectious diseases;(A00-A09);A90",
]

LIST_HEADER = (
    '"   ";"INTERNAL_ID";"CODING_SYSTEM";"CODE";"SEARCH_CODE";"PHRASE_ISL";"SEARCH_PHRASE_ISL";"PHRASE_ENGL";'
    '"SEARCH_PHRASE_ENGL";"TYPE";"STATUS";"NOTE_ENGL";"INCL_ENGL";"EXCL_ENGL";"TEXT_ENGL";"NOTE_ISL";"INCL_ISL";'
    '"EXCL_ISL";"TEXT_ISL";"SPECIAL";"FLAG";"CONSIDER_ENGL";"CONSIDER_ISL";"DEFINITION_ENGL";"DEFINITION_ISL";'
    '"SEARCH_STRING"'
)


LIST_COLUMNS = LIST_HEADER.replace('"', "").split(";")


def _list_row(number, code, phrase_isl, phrase_engl, row_type="C", status="1", **texts):
    """A list-file row; `texts` sets columns by name, e.g. INCL_ISL="..."."""
    values = {"   ": number, "INTERNAL_ID": number, "CODING_SYSTEM": "1", "CODE": code,
              "SEARCH_CODE": code.replace(".", ""), "PHRASE_ISL": phrase_isl, "SEARCH_PHRASE_ISL": phrase_isl.upper(),
              "PHRASE_ENGL": phrase_engl, "SEARCH_PHRASE_ENGL": phrase_engl.upper(), "TYPE": row_type,
              "STATUS": status, "SPECIAL": "0"}
    values.update(texts)
    return ";".join('"%s"' % values.get(column, "") for column in LIST_COLUMNS)


LIST_ROWS = [
    # The classification itself: a row the tree file does not have as a concept.
    _list_row("1", "ICD-10", "Alþjóðleg tölfræðiflokkun sjúkdóma", "International classification of diseases", "R"),
    _list_row("2", "I (A00-B99)", "I. kafli - Tilteknir smit- og sníklasjúkdómar",
              "Chapter I - Certain infectious and parasitic diseases", "H"),
    _list_row("3", "(A00-A09)", "Smitsjúkdómar í görnum", "Intestinal infectious diseases", "H"),
    _list_row("4", "A00", "Kólera", "Cholera", "H", INCL_ISL="Innifalið: kólera", EXCL_ENGL="Excl.: not cholera",
              EXCL_ISL="Útilokar:\n• kóleru† (A00.9)",
              NOTE_ENGL="Note for A00", DEFINITION_ISL="Skilgreining"),
    _list_row("5", "A00.0", "Kólera af völdum Vibrio cholerae 01, biovar cholerae",
              "Cholera due to Vibrio cholerae 01, biovar cholerae", TEXT_ISL="Hefðbundin\nkólera"),
    # Retired by Landlæknir.
    _list_row("6", "A00.1", "Kólera af völdum Vibrio cholerae 01, biovar eltor",
              "Cholera due to Vibrio cholerae 01, biovar eltor", status="0"),
]


def write_pair(directory, tree_rows=None, list_rows=None):
    """Write the two export files into `directory` and return (tree_path, list_path)."""
    tree_path = os.path.join(directory, "ICD10_tré.csv")
    list_path = os.path.join(directory, "ICD10_listi.csv")
    _write(tree_path, [TREE_HEADER] + (TREE_ROWS if tree_rows is None else tree_rows))
    _write(list_path, [LIST_HEADER] + (LIST_ROWS if list_rows is None else list_rows))
    return tree_path, list_path


def _write(path, lines):
    with open(path, "w", encoding="cp1252", newline="") as file:
        file.write("\r\n".join(lines) + "\r\n")
