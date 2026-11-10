"""Repair known kinds of "office mess" in a parsed document, BEFORE it is chunked.

Where this file sits in step 6:
    6.1 parsing:  file -> DoclingDocument
    cleanup:      DoclingDocument -> the same DoclingDocument, repaired   (THIS FILE)
    6.2 chunking: DoclingDocument -> list[Chunk]

Each repair is a small rule for one common way non-technical authors format documents.
The rules change only the STRUCTURE (what counts as a heading, which rows belong to which table);
they never change the text itself, so no price or time can be altered by a repair.

------------------------------------------------------------------------------------------------
Shape of `doc` (a DoclingDocument): the object both repairs receive and change.
Real values from the house rules (Word) and the spa price list (PDF).

  doc.texts : list of every piece of TEXT in the document, in reading order. Each one is an
              object whose class says what kind of text it is:
      [
          TitleItem(        label="title",          text="House Rules & Policies"),
          TextItem(         label="text",           text="1. Smoking",       formatting=Formatting(bold=True)),
          TextItem(         label="text",           text="The Overlook is entirely non-smoking, ...",
                                                    formatting=Formatting(bold=False)),
          ListItem(         label="list_item",      text="A valid credit card is required at check-in."),
          SectionHeaderItem(label="section_header", text="5. Cancellation policy", level=1),
          ...
      ]
      Each item also has: self_ref  its own address in the document, e.g. "#/texts/3" (= item 3 of doc.texts)
                          prov      where it came from: a list of ProvenanceItem(page_no=1, ...); [] in Word files

  doc.tables : list of every TABLE in the document. Each one is a TableItem:
      [
          TableItem(self_ref="#/tables/0", prov=[ProvenanceItem(page_no=1, ...)],
                    data=TableData(num_rows=16, num_cols=3, table_cells=[
                        TableCell(text="Treatment",       start_row_offset_idx=0, start_col_offset_idx=0, column_header=True),
                        TableCell(text="Duration",        start_row_offset_idx=0, start_col_offset_idx=1, column_header=True),
                        TableCell(text="Price",           start_row_offset_idx=0, start_col_offset_idx=2, column_header=True),
                        TableCell(text="MASSAGES",        start_row_offset_idx=1, start_col_offset_idx=0, column_header=False),
                        TableCell(text="Swedish massage", start_row_offset_idx=2, start_col_offset_idx=0, column_header=False),
                        TableCell(text="50 min",          start_row_offset_idx=2, start_col_offset_idx=1, column_header=False),
                        TableCell(text="$145",            start_row_offset_idx=2, start_col_offset_idx=2, column_header=False),
                        ...
                    ])),
          TableItem(self_ref="#/tables/1", prov=[ProvenanceItem(page_no=2, ...)],
                    data=TableData(num_rows=11, num_cols=3, table_cells=[
                        TableCell(text="BODY TREATMENTS", start_row_offset_idx=0, ..., column_header=False),
                        ...
                    ])),
      ]
      (data.grid shows the same cells arranged as rows: [["Treatment", "Duration", "Price"],
       ["MASSAGES", "", ""], ["Swedish massage", "50 min", "$145"], ...])

  doc.iterate_items() : walks through the document's CONTENT in reading order, texts and tables
      mixed, skipping page headers/footers. It gives pairs (item, level):
      ...
      (SectionHeaderItem(text="Treatments"), 1),
      (TableItem(self_ref="#/tables/0"), 1),
      (TableItem(self_ref="#/tables/1"), 1),
      (TextItem(text="Gift cards are available at the front desk."), 1),
------------------------------------------------------------------------------------------------
"""

import re

from docling_core.types.doc.document import DoclingDocument, SectionHeaderItem, TableItem, TextItem
from docling_core.types.doc.labels import DocItemLabel

# --- Fix 1: hand-made numbered headings ---------------------------------------------------------
#
# The problem (house rules, Word file): the author made headings by typing "7. Transportation"
# and clicking Bold, instead of using Word's "Heading" style. A person sees a heading; the file
# stores an ordinary paragraph (a TextItem, see the shape above). So the chunker starts no new
# piece there, and "7. Transportation" ends up inside the "5. Cancellation policy" piece.
#
# The rule: a paragraph is really a heading when ALL of these are true:
#   - it starts with a number and a dot, then text:   "7. Transportation"
#   - it is short (a heading, not a sentence):        under 60 characters
#   - the whole line is bold:                         item.formatting.bold is True
#
# Real examples from the house rules:
#   TextItem(text="1. Smoking", bold)                              -> becomes a heading
#   SectionHeaderItem(text="5. Cancellation policy")               -> already a heading, untouched
#   ListItem(text="Free cancellation up to 7 days before arrival.") -> not a paragraph, untouched
#
# Known limitation: this encodes one way of faking headings; see CLAUDE.md for the production
# alternatives (a more general rule, or an LLM structure pass).

NUMBERED_HEADING = re.compile(r"^\d+\.\s+\S")   # a number, a dot, a space, then text
MAX_HEADING_LENGTH = 60


def looks_like_numbered_heading(item: TextItem) -> bool:
    """
    True when a plain paragraph is really a hand-made numbered heading (see the rule above).

    Example: TextItem(label="text", text="7. Transportation", formatting=Formatting(bold=True)) -> True
    """
    is_bold = item.formatting is not None and item.formatting.bold
    return (
        item.label == DocItemLabel.TEXT                 # only plain paragraphs (not list items, not headings)
        and len(item.text) < MAX_HEADING_LENGTH
        and NUMBERED_HEADING.match(item.text) is not None
        and is_bold
    )


def promote_numbered_headings(doc: DoclingDocument) -> list[str]:
    """
    Turn every hand-made numbered heading into a real heading, in place (doc itself is changed).

    Shape returned: the headings that were promoted, in document order
      ["1. Smoking", "2. Pets", "3. Quiet hours", "4. Payment", "6. Arrival", ...]
    """
    promoted: list[str] = []

    # enumerate(doc.texts) gives each text item together with its position in the list:
    #   (0, TitleItem(text="House Rules & Policies"))
    #   (1, TextItem(text="Last updated: February 14, 2026"))
    #   (2, TextItem(text="We want every guest to enjoy ..."))
    #   (3, TextItem(text="1. Smoking", bold))            <- passes the rule
    #   ...
    # We need the position to put the new heading back in exactly the same place.
    for position, item in enumerate(doc.texts):
        if isinstance(item, TextItem) and looks_like_numbered_heading(item):

            # item.model_dump() = all of the paragraph's data as a plain dictionary
            # (model_dump is Pydantic's "turn this object into a dict"):
            #   {
            #       "self_ref": "#/texts/3",            # its address: item 3 of doc.texts
            #       "parent":   {"$ref": "#/texts/0"},  # it belongs under the title
            #       "label":    "text",
            #       "text":     "1. Smoking",
            #       "formatting": {"bold": True, "italic": False, ...},
            #       "prov": [],                         # no pages in a Word file
            #       ...
            #   }
            data = item.model_dump()

            # Change its kind to heading and give it a level (1 = top-level heading, the same
            # level as the one real heading in this document, "5. Cancellation policy"):
            #   {"self_ref": "#/texts/3", ..., "label": "section_header", "text": "1. Smoking", "level": 1}
            data["label"] = DocItemLabel.SECTION_HEADER
            data["level"] = 1

            # Build a heading object from that dictionary (model_validate = Pydantic's "build an
            # object of this class from this data") and put it in the same position:
            #   doc.texts[3] was  TextItem(text="1. Smoking")
            #   doc.texts[3] is   SectionHeaderItem(text="1. Smoking", level=1)
            doc.texts[position] = SectionHeaderItem.model_validate(data)
            promoted.append(item.text)
    return promoted


# --- Fix 2: tables that continue onto the next page ---------------------------------------------
#
# The problem (spa price list, PDF): the treatments table starts on page 1 and continues on page 2.
# Docling reads PDFs page by page, so doc.tables holds TWO tables (see the shape at the top):
#   table 0, page 1: header row "Treatment | Duration | Price", then massages and facials
#   table 1, page 2: NO header row; "BODY TREATMENTS", "EXTRAS", "PACKAGES" ...
# Without the header row, the second half is written out as "Rocky Mountain clay wrap, 1 = 80 min,
# 2 = $185": the prices lose their column names ("Duration", "Price").
#
# The rule: table B is the continuation of table A when ALL of these are true:
#   - B comes right after A in reading order (nothing but page headers/footers in between);
#   - B starts on the page right after the one where A ends;
#   - they have the same number of columns;
#   - B has no header row of its own (no cell with column_header=True).
# Then B's cells are added at the bottom of A (so they share A's header row) and B is removed.


def _pages(table: TableItem) -> list[int]:
    """
    The page numbers a table appears on.
    Example: TableItem(prov=[ProvenanceItem(page_no=1), ProvenanceItem(page_no=2)]) -> [1, 2]
    """
    return sorted({prov.page_no for prov in table.prov})


def _is_continuation(first: TableItem, second: TableItem) -> bool:
    """
    True when `second` is the rest of `first` on the next page (see the rule above).
    Example: first = table 0 (page 1, 3 columns, header row), second = table 1 (page 2, 3 columns,
    no header row) -> True
    """
    first_pages, second_pages = _pages(first), _pages(second)
    return (
        bool(first_pages) and bool(second_pages)
        and second_pages[0] == first_pages[-1] + 1
        and second.data.num_cols == first.data.num_cols
        and not any(cell.column_header for cell in second.data.table_cells)
    )


def stitch_continued_tables(doc: DoclingDocument) -> list[str]:
    """
    Join every table that continues onto the next page back into one table, in place.
    Repeats until nothing changes, so a table spread over 3 pages is joined too.

    Shape returned: one description per join, e.g.
      ["joined 11 rows from page 2 onto the table on page 1"]
    """
    joins: list[str] = []
    changed = True
    while changed:
        changed = False

        # The content in reading order (iterate_items gives (item, level) pairs; we keep the item):
        #   items = [..., SectionHeaderItem("Treatments"), TableItem("#/tables/0"),
        #                 TableItem("#/tables/1"), TextItem("Gift cards are available ...")]
        items = [item for item, _level in doc.iterate_items()]

        # zip(items, items[1:]) pairs each item with the next one (its neighbour):
        #   (SectionHeaderItem("Treatments"), TableItem("#/tables/0"))
        #   (TableItem("#/tables/0"),         TableItem("#/tables/1"))   <- two tables in a row
        #   (TableItem("#/tables/1"),         TextItem("Gift cards ..."))
        for first, second in zip(items, items[1:]):
            if isinstance(first, TableItem) and isinstance(second, TableItem) and _is_continuation(first, second):

                # Move every cell of the second table below the first table's rows.
                # The first table has 16 rows (rows 0..15), so offset = 16:
                #   TableCell(text="BODY TREATMENTS", start_row_offset_idx=0)              (second table)
                #   -> copy with start_row_offset_idx=16, appended to the first table's cells
                #   TableCell(text="Juniper and sage body scrub", start_row_offset_idx=1)
                #   -> copy with start_row_offset_idx=17, ...
                offset = first.data.num_rows
                for cell in second.data.table_cells:
                    moved = cell.model_copy()                    # model_copy = Pydantic's "copy this object"
                    moved.start_row_offset_idx += offset
                    moved.end_row_offset_idx += offset
                    first.data.table_cells.append(moved)
                first.data.num_rows += second.data.num_rows      # 16 + 11 = 27 rows

                # The first table now also records page 2:
                #   prov = [ProvenanceItem(page_no=1), ProvenanceItem(page_no=2)]  -> pages [1, 2]
                first.prov.extend(second.prov)

                joins.append(f"joined {second.data.num_rows} rows from page {_pages(second)[0]} "
                             f"onto the table on page {_pages(first)[0]}")

                # Remove the second table from the document: doc.tables goes from 2 tables to 1.
                doc.delete_items(node_items=[second])
                changed = True
                break                                            # the document changed: walk it again from the start
    return joins
