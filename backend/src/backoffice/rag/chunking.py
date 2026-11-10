"""Cut each parsed document into small pieces of text ("chunks"), one per section.

Where this file sits in step 6:
    6.1 parsing:   file             -> DoclingDocument  (one object per document: doc.texts + doc.tables)
    6.2 chunking:  DoclingDocument  -> list[Chunk]      (THIS FILE: small pieces, each with its headings)
    6.3 labels, 6.4 embeddings and saving to Postgres come after.

Why cut documents into pieces: when a guest asks "is the hedge maze open in August?", we want to
find the one paragraph about the maze, not the whole guest information sheet.

Who does what:
  - Docling's HybridChunker does the actual cutting. It walks through the document in order and
    starts a new piece at each heading; a piece that is too long (over MAX_TOKENS) is split, and
    small neighbouring pieces under the same heading are joined (merge_peers=True).
  - This file then copies each piece into OUR simple Chunk (see the class below for why).
"""

from dataclasses import dataclass, field

# Each class is imported from the Docling file where it is defined. (Shorter import paths also
# work when the code runs, but the editor flags them as "not exported".)
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
    DocChunk,
)
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.transforms.serializer.markdown import MarkdownParams, MarkdownTableSerializer
from docling_core.types.doc.document import DoclingDocument
from transformers import AutoTokenizer

# A "token" is roughly a word or a piece of a word: it's how language models count text length.
# The tokenizer below only MEASURES how long a piece is, so the chunker can respect MAX_TOKENS.
# It does not create embeddings (Voyage does that in 6.4). 256 tokens is our own choice: small
# pieces give precise search results.
TOKENIZER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MAX_TOKENS = 256


@dataclass
class Chunk:
    """
    OUR version of a chunk: the 5 plain fields the rest of the project uses.

    Docling's own piece (DocChunk) already holds the text, the headings and the file name, but
    the page numbers are buried inside it and the position number isn't stored at all. Copying
    each piece into this simple class, in one place, means:
      - every later step (labels, embeddings, the database table, the evidence view) works with
        5 plain fields, which are also the columns of the database table;
      - only this file depends on Docling. If we ever replace Docling, only this file changes.
    This is the "adapter" pattern: one place translates a library's format into our own.
    (queries.py does the same with database rows -> SupplierPrice.)
    """

    document: str                 # file name, e.g. "overlook_spa_price_list.pdf"
    index: int                    # position of the piece in its document: 0, 1, 2 ...
    headings: list[str]           # headings above the piece, e.g. ["Access to spa facilities"]
    text: str                     # the text of the piece (tables as Markdown rows: "| Swedish massage | 50 min | $145 |")
    pages: list[int] = field(default_factory=list)   # PDF pages it comes from, e.g. [1]; [] for Word files (no pages)
    label: str = ""               # contextual label written by Claude Haiku in step 6.3, e.g.
                                  # "Spa price list – treatment prices: extras and spa packages"; "" until then


# --- How tables are written into chunk text (fix 3) ----------------------------------------------
#
# A chunk is plain text, so the chunker has to "serialize" each table: write it out as text.
# Docling's DEFAULT way (TripletTableSerializer) turns every cell into a little sentence:
#     "Swedish massage, Duration = 50 min. Swedish massage, Price = $145."
# That's very wordy: the spa table overflowed the 256-token limit and was cut in the MIDDLE of a
# row, leaving pieces like "| - | Price = $135" (a price without its treatment name).
#
# We switch to Markdown table rows instead (MarkdownTableSerializer), one line per row:
#     | Treatment | Duration | Price |
#     |-|-|-|
#     | Swedish massage | 50 min | $145 |
# - about 3x fewer tokens, so tables are cut less often;
# - when a table still has to be cut, the chunker cuts between rows and, because
#   repeat_table_header is on (Docling's default), each piece starts again with the header row,
#   so no price is ever separated from its name or its column;
# - compact_tables=True removes the padding spaces Markdown adds to line columns up.
#
# How it plugs in: the chunker asks a "serializer provider" for the object that writes a document
# out as text. ChunkingSerializerProvider is Docling's standard one; we subclass it (make our own
# version) and change only one setting: which table serializer to use.


class MarkdownTablesProvider(ChunkingSerializerProvider):
    """Docling's standard chunking serializer, but with tables written as compact Markdown rows."""

    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(
            doc=doc,
            table_serializer=MarkdownTableSerializer(),
            params=MarkdownParams(compact_tables=True),
        )


def make_chunker(max_tokens: int = MAX_TOKENS) -> HybridChunker:
    """
    Build the "chunker": the object that does the cutting. Think of it as a machine you configure
    once and then feed one document after another. Its settings:
      - a tokenizer, to measure the length of each piece;
      - the maximum length of a piece (max_tokens);
      - merge_peers=True: join small neighbouring pieces that sit under the same heading;
      - serializer_provider: write tables as compact Markdown rows (see fix 3 above);
      - repeat_table_header=True: a table cut into several pieces repeats its header row in each.
    """
    tokenizer = HuggingFaceTokenizer(
        tokenizer=AutoTokenizer.from_pretrained(TOKENIZER_MODEL),   # downloaded once, then cached
        max_tokens=max_tokens,
    )
    return HybridChunker(
        tokenizer=tokenizer,
        merge_peers=True,
        serializer_provider=MarkdownTablesProvider(),
        repeat_table_header=True,
    )


def chunk_document(name: str, doc: DoclingDocument, chunker: HybridChunker) -> list[Chunk]:
    """
    Cut one parsed document into pieces and return them as our own Chunk objects.

    In:  name    = the file name, e.g. "overlook_spa_price_list.pdf"
         doc     = the DoclingDocument made by parsing (6.1)
         chunker = the machine made by make_chunker()

    Shape returned: list of Chunk objects, in document order (real output for the spa list)
      [
          Chunk(document="overlook_spa_price_list.pdf", index=0,
                headings=["Spa & Wellness Price List 2026"],
                text="Open daily from 9:00 AM to 8:00 PM (last treatment starts at 7:00 PM).",
                pages=[1]),
          Chunk(document="overlook_spa_price_list.pdf", index=1,
                headings=["Access to spa facilities"],
                text="- Hotel guests: free access to the sauna, steam room and relaxation area. ...",
                pages=[1]),
          ...
      ]
    """
    chunks: list[Chunk] = []   # the list we fill, one Chunk per piece

    # chunker.chunk(dl_doc=doc) does the cutting.
    #   - "dl_doc" is just the name of the parameter Docling's chunk() expects ("dl" = DocLing).
    #   - It gives back the pieces one at a time (like a conveyor belt), so we loop over them.
    # enumerate(...) numbers the pieces as they arrive: 0, 1, 2 ... That number becomes `index`.
    for index, piece in enumerate(chunker.chunk(dl_doc=doc)):

        # Each piece is a DocChunk: Docling's class for one piece of a document. It holds:
        #   piece.text           the text, e.g. "- Hotel guests: free access to the sauna ..."
        #   piece.meta.headings  the headings above it, e.g. ["Access to spa facilities"]
        #   piece.meta.doc_items the original items of the DoclingDocument it was made from,
        #                        e.g. the 3 bullet points of "Access to spa facilities"
        #
        # Why this check: Docling's code labels chunk() as returning the general parent class
        # (BaseChunk), which has no meta.doc_items, so the editor would flag the line below.
        # The pieces really ARE DocChunks; isinstance() confirms it, which tells the editor too.
        # If a future Docling version ever returned something else, we'd get this clear error.
        if not isinstance(piece, DocChunk):
            raise TypeError(f"Expected a DocChunk from HybridChunker, got {type(piece).__name__}")

        # Page numbers: every original item remembers where it came from ("prov", short for
        # provenance), including its page number (page_no). The 3 bullet points above give
        # [1, 1, 1]; the set {...} removes duplicates and sorted() gives [1]. Word files: [].
        pages = sorted({prov.page_no for item in piece.meta.doc_items for prov in item.prov})

        # Copy the piece into our own simple Chunk and add it to the list.
        chunks.append(Chunk(
            document=name,
            index=index,
            headings=list(piece.meta.headings or []),   # Docling gives None when there is no heading; we use []
            text=piece.text,
            pages=pages,
        ))
    return chunks
