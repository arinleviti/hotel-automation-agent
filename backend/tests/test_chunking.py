"""Chunking tests on the real spa price list: parse -> cleanup (fixes 1, 2) -> chunk (fix 3)."""

import pytest

from backoffice.rag.chunking import Chunk, chunk_document, make_chunker
from backoffice.rag.cleanup import promote_numbered_headings, stitch_continued_tables
from backoffice.rag.parsing import DOCUMENTS_DIR, parse_documents

SPA = "overlook_spa_price_list.pdf"
HEADER_ROW = "| Treatment | Duration | Price |"


@pytest.fixture(scope="module")
def spa_chunks() -> list[Chunk]:
    """
    The spa list's chunks, built once for all tests in this file (parsing a PDF takes seconds).

    Shape: list of Chunk, e.g.
      [Chunk(document="overlook_spa_price_list.pdf", index=3, headings=["Treatments"],
             text="| Treatment | Duration | Price |\n| - | - | - |\n| MASSAGES |  |  |\n| Swedish massage | 50 min | $145 |\n...",
             pages=[1, 2]),
       ...]
    """
    doc = parse_documents([DOCUMENTS_DIR / SPA])[SPA]
    promote_numbered_headings(doc)
    stitch_continued_tables(doc)
    return chunk_document(SPA, doc, make_chunker())


def table_chunks(chunks: list[Chunk]) -> list[Chunk]:
    return [c for c in chunks if "|" in c.text]


def test_tables_are_written_as_markdown_rows(spa_chunks):
    text = "\n".join(c.text for c in spa_chunks)

    assert "| Swedish massage | 50 min | $145 |" in text
    assert "Duration = " not in text                 # the old wordy format is gone


def test_every_table_piece_starts_with_the_header_row(spa_chunks):
    pieces = table_chunks(spa_chunks)

    assert len(pieces) >= 2                          # the table is long enough to be cut ...
    assert all(p.text.startswith(HEADER_ROW) for p in pieces)   # ... and each piece repeats the header


def test_no_price_is_separated_from_its_treatment(spa_chunks):
    # Every table line that contains a price must also contain a treatment name (first column).
    for piece in table_chunks(spa_chunks):
        for line in piece.text.splitlines():
            if "$" in line:
                first_cell = line.split("|")[1].strip()
                assert first_cell, f"price without a name: {line!r}"


def test_rows_from_both_pages_are_present(spa_chunks):
    text = "\n".join(c.text for c in spa_chunks)

    assert "| Men's facial | 50 min | $135 |" in text                  # page 1 (was orphaned before)
    assert "| Rocky Mountain clay wrap | 80 min | $185 |" in text      # page 2 (was "1 = 80 min" before)
