"""Tests for embeddings.py (fake Voyage client, no cost) and save_chunks (real database, rolled back)."""

from types import SimpleNamespace

import pytest

from backoffice.db.connection import connect
from backoffice.rag.chunking import Chunk
from backoffice.rag.embeddings import DIMENSIONS, VOYAGE_MODEL, embed_documents, embed_query, embedding_input
from backoffice.rag.index_documents import save_chunks

SAUNA = Chunk(document="overlook_spa_price_list.pdf", index=4, headings=["Treatments"],
              text="| Treatment | Duration | Price |\n| - | - | - |\n| Private sauna (up to 4 people) | 60 min | $90 |",
              pages=[1, 2], label="Spa price list 2026, Treatments table: extras such as the private sauna.")
TRANSPORT = Chunk(document="overlook_house_rules_and_policies.docx", index=7,
                  headings=["House Rules & Policies", "7. Transportation"],
                  text="The hotel does not run its own shuttle service.", pages=[],
                  label="House rules: transportation, no shuttle service, local taxi numbers.")


class FakeVoyage:
    """
    Stands in for voyageai.Client: records each request, returns vectors of the right size.
    Shape of a returned result: SimpleNamespace(embeddings=[[0.0, 0.0, ...1024 numbers], ...])
    """

    def __init__(self):
        self.requests: list[dict] = []

    def embed(self, texts, **options):
        self.requests.append({"texts": texts, **options})
        return SimpleNamespace(embeddings=[[0.001 * i] * DIMENSIONS for i in range(len(texts))])


def test_embedding_input_puts_the_label_first():
    assert embedding_input(SAUNA).splitlines()[:2] == [
        "Spa price list 2026, Treatments table: extras such as the private sauna.",
        "Treatments",
    ]


def test_documents_and_queries_use_the_right_input_type():
    fake = FakeVoyage()

    vectors = embed_documents(fake, ["chunk one", "chunk two"])
    query_vector = embed_query(fake, "is the hedge maze open in August?")

    assert len(vectors) == 2 and len(vectors[0]) == DIMENSIONS
    assert len(query_vector) == DIMENSIONS
    assert fake.requests[0]["model"] == VOYAGE_MODEL == "voyage-4"
    assert fake.requests[0]["input_type"] == "document"
    assert fake.requests[1]["input_type"] == "query"


def test_many_chunks_are_sent_in_batches():
    fake = FakeVoyage()

    vectors = embed_documents(fake, [f"chunk {i}" for i in range(130)])

    assert len(vectors) == 130
    assert [len(r["texts"]) for r in fake.requests] == [64, 64, 2]


@pytest.fixture
def conn():
    """A database connection, or skip if Postgres isn't running (same idea as test_db.py)."""
    try:
        connection = connect()
    except Exception as e:
        pytest.skip(f"Postgres not available ({type(e).__name__}): start it with `docker compose up -d`")
    yield connection
    connection.close()


def test_save_chunks_stores_rows_and_builds_the_keyword_index(conn):
    # force_rollback=True: everything written inside this block is undone at the end, so the real
    # index built by index_documents.py is left exactly as it was.
    with conn.transaction(force_rollback=True):
        save_chunks(conn, [SAUNA, TRANSPORT], [[0.01] * DIMENSIONS, [0.02] * DIMENSIONS])

        rows = conn.execute(
            "SELECT document, chunk_index, headings, pages, vector_dims(embedding) FROM chunks ORDER BY id"
        ).fetchall()
        # Shape of rows: [("overlook_spa_price_list.pdf", 4, ["Treatments"], [1, 2], 1024), ...]
        assert rows == [
            ("overlook_spa_price_list.pdf", 4, ["Treatments"], [1, 2], DIMENSIONS),
            ("overlook_house_rules_and_policies.docx", 7, ["House Rules & Policies", "7. Transportation"], [], DIMENSIONS),
        ]

        # The generated search_text column makes keyword search work with no extra code:
        found = conn.execute(
            "SELECT document FROM chunks WHERE search_text @@ plainto_tsquery('english', 'taxi')"
        ).fetchall()
        assert found == [("overlook_house_rules_and_policies.docx",)]


def test_save_chunks_refuses_mismatched_lengths(conn):
    with pytest.raises(ValueError):
        save_chunks(conn, [SAUNA, TRANSPORT], [[0.01] * DIMENSIONS])
