"""Prepare the hotel documents for search, in one command (step 6, "Part A" in CLAUDE.md).

Run (from backend/, with Docker running):  uv run python -m backoffice.rag.index_documents

    data/documents/*.pdf, *.docx
      1. parse    (Docling)                      -> DoclingDocument per file
      2. cleanup  (our rules: fixes 1 and 2)     -> the same DoclingDocument, repaired
      3. chunk    (Docling HybridChunker)        -> list[Chunk]
      4. label    (Claude Haiku)                 -> list[Chunk] with .label filled in
      5. embed    (Voyage)                       -> one vector per chunk
      6. save     (Postgres, one transaction)    -> the `chunks` table, emptied and refilled

Re-run it whenever a document is added, removed or replaced: the table is rebuilt from scratch, so
it always matches the files in data/documents/ exactly (the "swappable documents" rule).
"""

import sys

import psycopg

from backoffice.db.connection import connect
from backoffice.db.schema import apply_schema
from backoffice.rag.chunking import Chunk, chunk_document, make_chunker
from backoffice.rag.cleanup import promote_numbered_headings, stitch_continued_tables
from backoffice.rag.contextual_chunk_labels import label_chunks, make_client
from backoffice.rag.embeddings import embed_documents, embedding_input, make_voyage_client
from backoffice.rag.parsing import list_documents, parse_documents


def build_labelled_chunks() -> list[Chunk]:
    """
    Steps 1 to 4 for every document: parse, clean up, chunk, label.

    Shape returned: all chunks of all documents, labelled
        [
            Chunk(document="overlook_guest_information.pdf", index=0, headings=["THE OVERLOOK HOTEL"],
                  text="Guest Information | Sidewinder, Colorado Welcome to The Overlook. ...", pages=[1],
                  label="Guest information sheet welcome and introduction for The Overlook Hotel ..."),
            ...,
            Chunk(document="overlook_spa_price_list.pdf", index=4, headings=["Treatments"],
                  text="| Treatment | Duration | Price |\n...", pages=[1, 2],
                  label="Spa price list 2026, Treatments table: extras such as private sauna ..."),
        ]
    """
    claude = make_client()
    chunker = make_chunker()
    all_chunks: list[Chunk] = []
    for name, doc in parse_documents(list_documents()).items():
        promote_numbered_headings(doc)
        stitch_continued_tables(doc)
        chunks = chunk_document(name, doc, chunker)
        # The whole document as Markdown is what Claude reads to write each label (and what gets cached).
        labelled, _usages = label_chunks(claude, doc.export_to_markdown(), chunks)
        all_chunks.extend(labelled)
    return all_chunks


def save_chunks(conn: psycopg.Connection, chunks: list[Chunk], vectors: list[list[float]]) -> None:
    """
    Step 6: replace the contents of the `chunks` table, all-or-nothing (one transaction).

    `chunks` and `vectors` are in the same order: vectors[i] is the embedding of chunks[i].
    """
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")

    with conn.transaction():
        apply_schema(conn)                        # creates the table and indexes if they don't exist yet
        conn.execute("TRUNCATE chunks RESTART IDENTITY")   # empty it; ids start again from 1
        with conn.cursor() as cur:
            cur.executemany(
                # ::text[] / ::integer[] / ::vector tell Postgres the type of each value:
                #   headings ["Treatments"]  -> text[] {'Treatments'}
                #   pages    []              -> integer[] {}   (an empty list has no type on its own)
                #   vector   "[0.0123, -0.0456, ...]" (written as text) -> vector(1024)
                "INSERT INTO chunks (document, chunk_index, headings, text, pages, label, embedding)"
                " VALUES (%s, %s, %s::text[], %s, %s::integer[], %s, %s::vector)",
                [
                    (c.document, c.index, c.headings, c.text, c.pages, c.label, str(vector))
                    for c, vector in zip(chunks, vectors)
                ],
            )


def main() -> int:
    print("Parsing, cleaning up, chunking and labelling the documents ...")
    chunks = build_labelled_chunks()

    print(f"Embedding {len(chunks)} chunks with Voyage ...")
    vectors = embed_documents(make_voyage_client(), [embedding_input(c) for c in chunks])

    with connect() as conn:
        save_chunks(conn, chunks, vectors)

    documents = sorted({c.document for c in chunks})
    print(f"Indexed {len(chunks)} chunks from {len(documents)} documents: {', '.join(documents)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
