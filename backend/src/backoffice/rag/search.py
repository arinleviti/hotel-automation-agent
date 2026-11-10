"""Search the hotel documents for a question (step 7). The question agent's tool in step 12.

The search is a two-stage funnel:

    question
      a. embed the question                       Voyage voyage-4 (input_type="query")
      b. vector search: the 8 closest chunks      LOCAL, in Postgres (pgvector compares numbers)
      c. rerank those 8                           Voyage rerank-3-lite reads question + each chunk TOGETHER
      d. keep the best 4                          -> returned to the caller (the agent, the evidence view)

Why two stages: vector search is fast and could scan thousands of chunks, but it compares two
summaries (vectors) made separately. The reranker judges "does this chunk answer this question?"
precisely, but has to read every pair from scratch, so it only gets the shortlist.

Every result keeps its evidence (document, headings, pages, both scores), so the demo can show
which document and section an answer came from, and how confident the search was.
"""

from dataclasses import dataclass

import psycopg
import voyageai

from backoffice.rag.chunking import Chunk
from backoffice.rag.embeddings import embed_query, embedding_input

RERANK_MODEL = "rerank-3-lite"   # decided in CLAUDE.md: free at our size, good results in our tests
VECTOR_CANDIDATES = 8            # how many chunks vector search hands to the reranker
RESULTS = 4                      # how many the reranker keeps


@dataclass
class SearchResult:
    """
    One chunk found for a question, with its evidence.

    Example (email #7, "Can my 10-year-old use the pool on his own ...?"):
        SearchResult(chunk_id=19, document="overlook_house_rules_and_policies.docx",
                     headings=["House Rules & Policies", "9. Children"], pages=[],
                     label="House rules: children policy covering pool supervision for under-14s ...",
                     text="Children under 14 must be accompanied by an adult at the pool. ...",
                     vector_similarity=0.40, rerank_score=0.64)
    """

    chunk_id: int               # the row id in the chunks table
    document: str
    headings: list[str]
    pages: list[int]            # [] for the Word file
    label: str
    text: str
    vector_similarity: float    # stage b: 1 = same meaning, 0 = unrelated (cosine similarity)
    rerank_score: float         # stage c: the reranker's relevance score, 0..1; the one to trust


def vector_candidates(conn: psycopg.Connection, question_vector: list[float], limit: int) -> list[SearchResult]:
    """
    Stage b: the `limit` chunks whose embedding is closest to the question's.

    `embedding <=> %s::vector` is pgvector's COSINE DISTANCE operator: 0 = pointing the same way
    (same meaning), up to 2 = opposite. ORDER BY it = closest first. We report 1 - distance as a
    similarity (1 = same meaning). rerank_score is filled in by stage c (0.0 until then).

    Shape of the rows from Postgres: list of tuples
        [(19, "overlook_house_rules_and_policies.docx", ["House Rules & Policies", "9. Children"], [],
          "House rules: children policy ...", "Children under 14 must be ...", 0.40), ...]
    """
    vector_text = str(question_vector)    # "[0.0311, -0.0087, ...]": pgvector reads a vector written as text
    rows = conn.execute(
        "SELECT id, document, headings, pages, label, text, 1 - (embedding <=> %s::vector) AS similarity"
        " FROM chunks ORDER BY embedding <=> %s::vector LIMIT %s",
        (vector_text, vector_text, limit),
    ).fetchall()
    return [
        SearchResult(chunk_id=i, document=d, headings=h, pages=p, label=l, text=t,
                     vector_similarity=float(s), rerank_score=0.0)
        for i, d, h, p, l, t, s in rows
    ]


def rerank(voyage: voyageai.Client, question: str, candidates: list[SearchResult], keep: int) -> list[SearchResult]:
    """
    Stage c: the reranker reads the question with each candidate and keeps the best `keep`.

    The reranker gets the same text that was embedded for each chunk (label + headings + text).
    voyage.rerank(...) answers with one result per kept candidate, best first; each result says
    which candidate it is (`index`, its position in the list we sent) and its relevance_score:
        result.results = [RerankingResult(index=1, relevance_score=0.66, ...),
                          RerankingResult(index=2, relevance_score=0.64, ...), ...]

    Shape returned: the kept candidates, best first, with rerank_score filled in.
    """
    if not candidates:
        return []
    texts = [
        embedding_input(Chunk(document=c.document, index=0, headings=c.headings, text=c.text, label=c.label))
        for c in candidates
    ]
    result = voyage.rerank(question, texts, model=RERANK_MODEL, top_k=keep)
    ranked: list[SearchResult] = []
    for item in result.results:
        candidate = candidates[item.index]
        candidate.rerank_score = float(item.relevance_score)
        ranked.append(candidate)
    return ranked


def search_documents(
    conn: psycopg.Connection,
    voyage: voyageai.Client,
    question: str,
    candidates: int = VECTOR_CANDIDATES,
    keep: int = RESULTS,
) -> list[SearchResult]:
    """
    The whole search: a. embed the question -> b. vector search -> c. rerank -> d. best `keep`.

    The connection and the Voyage client are passed in (not created here), like the services'
    data: tests can pass fakes, and the agent can reuse one connection for several searches.

    Shape returned: up to `keep` SearchResult, best first. Real example for email #6
    ("Do you have an indoor pool, and how much is the spa?"):
        [SearchResult(document="overlook_spa_price_list.pdf", headings=["Access to spa facilities"], rerank_score=0.77, ...),
         SearchResult(document="overlook_guest_information.pdf", headings=["Indoor pool"], rerank_score=0.66, ...),
         SearchResult(document="overlook_spa_price_list.pdf", headings=["Treatments"], rerank_score=0.57, ...),
         SearchResult(document="overlook_guest_information.pdf", headings=["Spa"], rerank_score=0.54, ...)]
    """
    question_vector = embed_query(voyage, question)                    # a.
    shortlist = vector_candidates(conn, question_vector, candidates)   # b.
    return rerank(voyage, question, shortlist, keep)                   # c. + d.
