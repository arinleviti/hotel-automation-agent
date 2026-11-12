"""The question agent's search tool: your step-7 search, offered to the LLM as a tool.

A tool has three parts; this file holds one of each:
  SEARCH_TOOL                     the DESCRIPTION the model reads: name "search_documents", what it does,
                                  its input {query}. Sent to Claude on every agent turn.
  run_search_tool(query)          RUNS the search -> SearchRecord (kept in the state: evidence, answer checks)
  format_results_for_llm(results) turns the results into the TEXT the model reads back

They don't call each other: the search_step node (graph/branches/question/agent.py) calls the two
functions one after the other, because their outputs go to different places:
    record = run_search_tool(query)                 -> structured results, into the state
    text = format_results_for_llm(record.results)   -> text, back to the model

The name "search_documents" appears twice elsewhere, for two different things:
    the model writes:  search_documents("hedge maze")                   <- the TOOL's name
      -> search_step -> run_search_tool("hedge maze")                   <- this file
           -> search_documents(conn, voyage, "hedge maze")              <- rag/search.py, step 7: Voyage embeds
                                                                           the query -> pgvector top 8 -> rerank -> best 4
      -> format_results_for_llm(...)                                    <- this file
"""

# --- Where every name used in this file comes from ------------------------------------------------
# OURS:
from backoffice.db.connection import connect                          # open a Postgres connection
from backoffice.graph.state import SearchRecord
from backoffice.rag.embeddings import make_voyage_client               # the Voyage API client
from backoffice.rag.search import SearchResult, search_documents       # step 7: embed -> vector top 8 -> rerank -> 4

# A tool definition in the Anthropic Messages API format:
#   name          what the model writes in its tool call
#   description   tells the model WHEN and HOW to use it (the model reads this, like a prompt)
#   input_schema  the JSON Schema its input must match
#   strict: True  the API guarantees the model's input matches the schema exactly
#                 (strict mode requires "additionalProperties": false and every field in "required")
SEARCH_TOOL = {
    "name": "search_documents",
    "description": (
        "Search The Overlook Hotel's documents (guest information, house rules, spa price list, room rates) "
        "for passages about ONE topic. Returns the 4 most relevant passages, each with its chunk number and a "
        "relevance score from 0 to 1 (below about 0.5 the passage is probably not about your topic). "
        "Search separately for each thing the guest asks about; if the results don't fit, search again with "
        "other words."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for, in a few words, e.g. 'indoor pool opening hours'."},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}


def run_search_tool(query: str) -> SearchRecord:
    """
    Run one search for the agent (Postgres + Voyage, both real; swapped for a fake in tests).

    Example: run_search_tool("hedge maze opening months")
        -> SearchRecord(query="hedge maze opening months",
                        results=[SearchResult(chunk_id=7, document="overlook_guest_information.pdf",
                                              headings=["Hedge maze"], pages=[2], ..., rerank_score=0.66), ...])
    """
    with connect() as conn:
        return SearchRecord(query=query, results=search_documents(conn, make_voyage_client(), query))


def format_results_for_llm(results: list[SearchResult]) -> str:
    """
    The search results as the text the agent reads (the tool's answer).

    Example (one result):
        [chunk 7] overlook_guest_information.pdf > Hedge maze (page 2), relevance 0.66
        Hedge maze. Our hedge maze in the east gardens is open from June to September, 9 AM to sunset ...
    """
    if not results:
        return "No passages found."
    blocks = []
    for r in results:
        where = " > ".join(r.headings) if r.headings else "(no heading)"
        pages = f" (page {', '.join(map(str, r.pages))})" if r.pages else ""
        blocks.append(f"[chunk {r.chunk_id}] {r.document} > {where}{pages}, relevance {r.rerank_score:.2f}\n{r.text}")
    return "\n\n".join(blocks)
