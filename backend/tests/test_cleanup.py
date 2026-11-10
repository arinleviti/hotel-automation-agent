"""Tests for the document repairs in rag/cleanup.py."""

from docling_core.types.doc.base import BoundingBox
from docling_core.types.doc.document import (
    DoclingDocument,
    Formatting,
    ProvenanceItem,
    SectionHeaderItem,
    TableCell,
    TableData,
)
from docling_core.types.doc.labels import DocItemLabel

from backoffice.rag.chunking import chunk_document, make_chunker
from backoffice.rag.cleanup import promote_numbered_headings, stitch_continued_tables
from backoffice.rag.parsing import DOCUMENTS_DIR, parse_documents

BOLD = Formatting(bold=True)


def small_house_rules() -> DoclingDocument:
    """
    A tiny DoclingDocument built by hand, shaped like the real house rules:
      "7. Transportation" (bold paragraph) -> its text -> "Free cancellation ..." (not bold)
    """
    doc = DoclingDocument(name="test")
    doc.add_text(label=DocItemLabel.TEXT, text="7. Transportation", formatting=BOLD)
    doc.add_text(label=DocItemLabel.TEXT, text="The hotel does not run its own shuttle service.")
    doc.add_text(label=DocItemLabel.TEXT, text="1. Free cancellation up to 7 days before arrival.")   # numbered, NOT bold
    doc.add_text(label=DocItemLabel.TEXT, text="12. This line is bold and numbered but far too long to be a heading",
                 formatting=BOLD)
    return doc


def test_bold_numbered_short_line_becomes_a_heading():
    doc = small_house_rules()

    promoted = promote_numbered_headings(doc)

    assert promoted == ["7. Transportation"]
    assert isinstance(doc.texts[0], SectionHeaderItem)
    assert doc.texts[0].level == 1
    assert doc.texts[0].text == "7. Transportation"          # the text itself is unchanged


def test_numbered_line_that_is_not_bold_stays_a_paragraph():
    doc = small_house_rules()
    promote_numbered_headings(doc)

    assert doc.texts[2].label == DocItemLabel.TEXT            # "1. Free cancellation ..." untouched


def test_long_bold_numbered_line_stays_a_paragraph():
    doc = small_house_rules()
    promote_numbered_headings(doc)

    assert doc.texts[3].label == DocItemLabel.TEXT


def test_real_house_rules_get_one_chunk_per_numbered_section():
    # The real Word file: no layout models involved for .docx, so this is quick.
    name = "overlook_house_rules_and_policies.docx"
    doc = parse_documents([DOCUMENTS_DIR / name])[name]

    promoted = promote_numbered_headings(doc)
    chunks = chunk_document(name, doc, make_chunker())

    assert promoted == ["1. Smoking", "2. Pets", "3. Quiet hours", "4. Payment",
                        "6. Arrival", "7. Transportation", "8. Damage and lost property", "9. Children"]
    transport = [c for c in chunks if "7. Transportation" in c.headings]
    assert len(transport) == 1
    assert "shuttle" in transport[0].text
    assert "Cancellation" not in transport[0].text          # no longer mixed with the cancellation policy


# --- Fix 2: stitch_continued_tables -----------------------------------------------------------


def table_data(rows: list[list[str]], header: bool) -> TableData:
    """
    Build Docling's TableData from plain rows. When `header` is True, the first row is marked
    as the column header row (like "Treatment | Duration | Price").

    Shape of `rows`: [["Treatment", "Duration", "Price"], ["Swedish massage", "50 min", "$145"], ...]
    """
    cells = [
        TableCell(text=text,
                  start_row_offset_idx=r, end_row_offset_idx=r + 1,
                  start_col_offset_idx=c, end_col_offset_idx=c + 1,
                  column_header=header and r == 0)
        for r, row in enumerate(rows)
        for c, text in enumerate(row)
    ]
    return TableData(table_cells=cells, num_rows=len(rows), num_cols=len(rows[0]))


def on_page(page: int) -> ProvenanceItem:
    """Where an item came from: only the page number matters for these tests."""
    return ProvenanceItem(page_no=page, bbox=BoundingBox(l=0, t=0, r=1, b=1), charspan=(0, 0))


def split_spa_table(second_page: int = 2, second_cols: int = 3) -> DoclingDocument:
    """
    A tiny DoclingDocument shaped like the real spa price list:
      page 1: table with header row + 1 massage;  page 2: its continuation, no header row.
    """
    doc = DoclingDocument(name="test")
    doc.add_table(data=table_data([["Treatment", "Duration", "Price"],
                                   ["Swedish massage", "50 min", "$145"]], header=True),
                  prov=on_page(1))
    second_rows = [["Rocky Mountain clay wrap", "80 min", "$185"][:second_cols]]
    doc.add_table(data=table_data(second_rows, header=False), prov=on_page(second_page))
    return doc


def test_continued_table_is_joined_under_the_first_header():
    doc = split_spa_table()

    joins = stitch_continued_tables(doc)

    assert joins == ["joined 1 rows from page 2 onto the table on page 1"]
    assert len(doc.tables) == 1
    grid = doc.tables[0].data.grid                    # the table as rows of cells
    assert [cell.text for cell in grid[0]] == ["Treatment", "Duration", "Price"]
    assert [cell.text for cell in grid[2]] == ["Rocky Mountain clay wrap", "80 min", "$185"]
    assert sorted({p.page_no for p in doc.tables[0].prov}) == [1, 2]


def test_tables_with_different_columns_are_not_joined():
    doc = split_spa_table(second_cols=2)

    assert stitch_continued_tables(doc) == []
    assert len(doc.tables) == 2


def test_tables_not_on_consecutive_pages_are_not_joined():
    doc = split_spa_table(second_page=3)

    assert stitch_continued_tables(doc) == []
    assert len(doc.tables) == 2


def test_real_spa_list_second_half_joins_the_first_table():
    # The real PDF (uses Docling's layout models: a few seconds).
    # Checks the TABLE itself, not how chunks write it out (that's tested in test_chunking.py).
    name = "overlook_spa_price_list.pdf"
    doc = parse_documents([DOCUMENTS_DIR / name])[name]

    stitch_continued_tables(doc)

    assert len(doc.tables) == 1
    rows = [[cell.text for cell in row] for row in doc.tables[0].data.grid]
    # Shape of rows: [["Treatment", "Duration", "Price"], ["MASSAGES", "", ""], ["Swedish massage", "50 min", "$145"], ...]
    assert len(rows) == 27
    assert rows[0] == ["Treatment", "Duration", "Price"]
    assert ["Rocky Mountain clay wrap", "80 min", "$185"] in rows      # a page-2 row, now under the header
