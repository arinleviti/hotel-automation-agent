"""Tests for rag/search.py.

- Unit tests: a fake Voyage client and a few fake chunks written inside a rolled-back transaction,
  so nothing is paid and the real index is never touched.
- Live tests (real Voyage + the real index) run only when RUN_LIVE_TESTS=1 is set, because they
  call a paid API:   $env:RUN_LIVE_TESTS = "1"; uv run pytest tests/test_search.py
"""

import os
from types import SimpleNamespace

import pytest

from backoffice.db.connection import connect
from backoffice.rag.chunking import Chunk
from backoffice.rag.embeddings import DIMENSIONS, make_voyage_client
from backoffice.rag.index_documents import save_chunks
from backoffice.rag.search import RERANK_MODEL, search_documents

# Three fake chunks with hand-made vectors. Each vector is "all zeros except one position", so we
# control which one is closest to the question: the question vector points mostly at position 0.
POOL = Chunk(document="guest.pdf", index=0, headings=["Indoor pool"], text="Heated indoor pool.", pages=[1], label="pool")
MAZE = Chunk(document="guest.pdf", index=1, headings=["Hedge maze"], text="Open June to September.", pages=[2], label="maze")
PETS = Chunk(document="rules.docx", index=0, headings=["2. Pets"], text="Pets are not allowed.", pages=[], label="pets")


def one_hot(position: int) -> list[float]:
    """A vector of 1024 zeros with a 1 at `position`, e.g. one_hot(0) = [1.0, 0.0, 0.0, ...]."""
    vector = [0.0] * DIMENSIONS
    vector[position] = 1.0
    return vector


class FakeVoyage:
    """
    Stands in for voyageai.Client.
      embed(...)  -> the question vector: close to POOL (position 0), a bit close to MAZE (position 1)
      rerank(...) -> prefers the candidate whose text mentions "June" (MAZE), to prove the reranker
                     can overturn the vector order. Shape of its answer:
                     SimpleNamespace(results=[SimpleNamespace(index=1, relevance_score=0.9), ...])
    """

    def __init__(self):
        self.rerank_requests: list[dict] = []

    def embed(self, texts, **options):
        question = [0.0] * DIMENSIONS
        question[0], question[1] = 1.0, 0.5
        return SimpleNamespace(embeddings=[question])

    def rerank(self, query, documents, model, top_k):
        self.rerank_requests.append({"query": query, "documents": documents, "model": model, "top_k": top_k})
        scores = [0.9 if "June" in text else 0.2 for text in documents]
        order = sorted(range(len(documents)), key=lambda i: scores[i], reverse=True)[:top_k]
        return SimpleNamespace(results=[SimpleNamespace(index=i, relevance_score=scores[i]) for i in order])


@pytest.fixture
def conn():
    try:
        connection = connect()
    except Exception as e:
        pytest.skip(f"Postgres not available ({type(e).__name__}): start it with `docker compose up -d`")
    yield connection
    connection.close()


def test_vector_search_shortlists_and_reranker_decides_the_order(conn):
    fake = FakeVoyage()
    with conn.transaction(force_rollback=True):          # fake chunks, undone at the end
        save_chunks(conn, [POOL, MAZE, PETS], [one_hot(0), one_hot(1), one_hot(2)])

        results = search_documents(conn, fake, "Is the maze open in summer?", candidates=2, keep=2)

    # Vector search shortlisted POOL and MAZE (the 2 closest), not PETS ...
    sent = fake.rerank_requests[0]["documents"]
    assert len(sent) == 2 and not any("Pets" in text for text in sent)
    # ... and the reranker put MAZE first, overturning the vector order (POOL was closer).
    assert [r.headings for r in results] == [["Hedge maze"], ["Indoor pool"]]
    assert results[0].rerank_score == 0.9
    assert results[1].vector_similarity > results[0].vector_similarity   # POOL was closer by vector


def test_reranker_gets_label_headings_and_text(conn):
    fake = FakeVoyage()
    with conn.transaction(force_rollback=True):
        save_chunks(conn, [MAZE], [one_hot(1)])
        search_documents(conn, fake, "maze?", candidates=1, keep=1)

    assert fake.rerank_requests[0]["model"] == RERANK_MODEL == "rerank-3-lite"
    assert fake.rerank_requests[0]["documents"] == ["maze\nHedge maze\nOpen June to September."]


# --- Live: the real index, the real Voyage API -------------------------------------------------

live = pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to call Voyage")


@live
@pytest.mark.parametrize(
    "question, must_find",
    [
        # email #6: pool + spa prices, from two documents
        ("Do you have an indoor pool, and how much is the spa?", {"Indoor pool", "Treatments"}),
        # email #7: the maze season and the children's pool rule
        ("Can my 10-year-old use the pool on his own, and is the hedge maze open in August?",
         {"Hedge maze", "9. Children"}),
    ],
)
def test_live_answerable_questions_find_their_sections(conn, question, must_find):
    results = search_documents(conn, make_voyage_client(), question)
    found = {r.headings[-1] for r in results}

    assert must_find <= found, f"expected {must_find} in {found}"


@live
def test_live_helicopter_question_scores_low(conn):
    # email #8: nothing answers it, so even the best chunk scores clearly lower than for answerable questions
    voyage = make_voyage_client()
    helicopter = search_documents(conn, voyage, "Can you organise a helicopter transfer from Denver International Airport?")
    spa = search_documents(conn, voyage, "Do you have an indoor pool, and how much is the spa?")

    assert helicopter[0].rerank_score < spa[0].rerank_score
