"""Turn text into vectors (embeddings) with Voyage AI.

An embedding is a list of numbers (here 1024) that captures what a text MEANS. Texts with similar
meaning get vectors that are close together, so "is the maze open in summer?" lands near the chunk
"Our hedge maze ... is open from June to September", even though they share few words.

Voyage is called in two moments only:
  - step 6.4 (this step): once per run, to embed all the chunks          -> embed_documents()
  - step 7 onward:        once per search, to embed the guest's question -> embed_query()
Both use the SAME model, so question vectors and chunk vectors can be compared.
"""

import voyageai

from backoffice.config import get_settings
from backoffice.rag.chunking import Chunk

VOYAGE_MODEL = "voyage-4"   # decided in CLAUDE.md: the balanced option ($0.06 / 1M tokens)
DIMENSIONS = 1024           # numbers per vector; must match vector(1024) in schema.sql
BATCH_SIZE = 64             # texts per request (Voyage accepts many; 28 chunks fit in one request)


def make_voyage_client() -> voyageai.Client:
    """The Voyage client: the object that sends texts to Voyage. Key from .env (VOYAGE_API_KEY)."""
    key = get_settings().voyage_api_key
    if key is None:
        raise RuntimeError("VOYAGE_API_KEY is missing: add it to the .env file at the repo root.")
    # timeout=30.0: a call taking more than 30 s raises voyageai.error.Timeout instead of hanging
    # (step 13: retried once by the graph's RETRY_ONCE, then the email goes to a person).
    # max_retries=0 is Voyage's default: retries are LangGraph's job.
    return voyageai.Client(api_key=key.get_secret_value(), timeout=30.0, max_retries=0)


def embedding_input(chunk: Chunk) -> str:
    """
    The text that gets embedded for one chunk: label first, then headings, then the chunk text.
    The label is what puts the chunk back in context (step 6.3).

    Example:
        "Spa price list 2026, Treatments table: extras such as private sauna and spa packages ...\n"
        "Treatments\n"
        "| Treatment | Duration | Price |\n| - | - | - |\n| Private sauna (up to 4 people) | 60 min | $90 |\n..."
    """
    return "\n".join([chunk.label, " > ".join(chunk.headings), chunk.text])


def embed_documents(client: voyageai.Client, texts: list[str]) -> list[list[float]]:
    """
    Embed the chunk texts (input_type="document": Voyage prepares each text as something to be found).

    Shape returned: one vector per text, in the same order as `texts`
        [
            [0.0123, -0.0456, 0.0789, ...],   # 1024 numbers for texts[0]
            [-0.0021, 0.0334, -0.0112, ...],  # 1024 numbers for texts[1]
            ...
        ]
    """
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):           # 0, 64, 128 ...: one request per batch
        batch = texts[start:start + BATCH_SIZE]
        # client.embed(...) = one request to Voyage. The answer's .embeddings is the list of vectors.
        result = client.embed(batch, model=VOYAGE_MODEL, input_type="document", output_dimension=DIMENSIONS)
        vectors.extend(result.embeddings)
    return vectors


def embed_query(client: voyageai.Client, question: str) -> list[float]:
    """
    Embed one search question (input_type="query": Voyage prepares it as a question looking for answers).
    Used from step 7.

    Shape returned: one vector, e.g. [0.0311, -0.0087, ...] (1024 numbers)
    """
    result = client.embed([question], model=VOYAGE_MODEL, input_type="query", output_dimension=DIMENSIONS)
    return result.embeddings[0]
