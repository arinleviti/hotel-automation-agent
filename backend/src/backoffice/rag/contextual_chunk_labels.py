"""Give every chunk a one-line CONTEXTUAL LABEL, written by Claude Haiku (step 6.3).

Where this file sits in step 6:
    6.1 parsing -> cleanup -> 6.2 chunking -> 6.3 contextual labels (THIS FILE) -> 6.4 embeddings + database

The problem it solves: a chunk cut out of its document can lose its meaning. Real example:
    Chunk(headings=["Treatments"],
          text="| Treatment | Duration | Price |\n| Private sauna (up to 4 people) | 60 min | $90 |\n| PACKAGES | ...")
Nothing in it says this is the SPA price list, so a guest asking "how much is the spa?" might not
find it. Claude reads the WHOLE document and writes one line that puts the chunk back in context:
    "Spa & wellness price list – treatment prices (part 2): extras such as the private sauna, and spa packages."
In 6.4 the label is embedded together with the chunk text, so the search can find it.
This technique is called "contextual retrieval" (published by Anthropic).

What is sent to Claude, once per chunk:
    system   = the instructions (identical for every call)
    user     = [ the whole document as Markdown   <- marked for prompt caching
                 the one chunk to label ]
The label is stored NEXT TO the chunk; the chunk's text is never changed.

Prompt caching: a document with 5 chunks is sent 5 times. The system prompt + document part is
identical each time, so Claude stores it after the first call ("cache write") and the next calls
read it from the cache ("cache read": cheaper and faster). Claude only caches a prefix of at least
512 tokens (for Haiku 5.5), so the shortest documents (e.g. the 1-page rate card) simply won't be
cached: no error, just no saving.
"""

from dataclasses import dataclass, replace

import anthropic

from backoffice.llm import anthropic_client
from backoffice.rag.chunking import Chunk

# Claude Haiku 5.5: the smallest, cheapest Claude model ($0.10 / $0.50 per million tokens in/out).
# Decided in CLAUDE.md: a simple, one-off task doesn't need a bigger model.
LABEL_MODEL = "claude-haiku-5-5"

# The instructions, identical for every call (so they can be part of the cached prefix).
SYSTEM_PROMPT = """You write contextual labels for chunks of a hotel's documents, to improve search.

You will be given a whole document, then one chunk taken from it. Write ONE line (at most 30 words)
that situates the chunk within the document, so the chunk can be found by search even when its own
text doesn't say what it is about.

The label must:
- start with the kind of document (e.g. "Spa price list", "House rules", "Guest information", "Room rate card");
- name the section the chunk belongs to and what the chunk covers;
- use words a guest might search with (e.g. "spa", "pool", "children", "cancellation", "transport").

The label must NOT:
- repeat prices, times or numbers from the chunk (the chunk itself already contains them);
- add any fact that is not in the document.

Answer with the label only: no quotes, no preamble."""


@dataclass
class LabelUsage:
    """
    Token counts for one call, to see prompt caching at work.
    Example, the 2nd chunk of the spa list: LabelUsage(cache_write=0, cache_read=812, uncached_input=61, output=27)
    """

    cache_write: int      # tokens stored in the cache by this call (first call for a document)
    cache_read: int       # tokens read from the cache (later calls for the same document)
    uncached_input: int   # input tokens sent at full price (the chunk + anything not cached)
    output: int           # tokens Claude wrote (thinking included)


def make_client() -> anthropic.Anthropic:
    """
    The Anthropic SDK client: the object that sends requests to Claude.
    Now created in one shared place (backoffice/llm.py), so every node uses the same client.
    """
    return anthropic_client()


def chunk_for_prompt(chunk: Chunk) -> str:
    """
    How one chunk is shown to Claude: its headings, then its text.

    Example:
        "Headings: Treatments\n\n| Treatment | Duration | Price |\n| - | - | - |\n| Private sauna (up to 4 people) | 60 min | $90 |\n..."
    """
    headings = " > ".join(chunk.headings) or "(none)"
    return f"Headings: {headings}\n\n{chunk.text}"


def write_label(client: anthropic.Anthropic, document_markdown: str, chunk: Chunk) -> tuple[str, LabelUsage]:
    """
    Ask Claude Haiku for one chunk's label.

    In:  document_markdown = the whole document as Markdown (the same string for every chunk of that
                             document: that's what makes caching work)
         chunk             = the chunk to label

    Shape returned: (label, usage)
        ("Spa price list – Treatments: extras (private sauna) and spa packages, with durations and prices.",
         LabelUsage(cache_write=0, cache_read=812, uncached_input=61, output=27))
    """
    # client.messages.create(...) = one request to Claude (the Messages API).
    response = client.messages.create(
        model=LABEL_MODEL,
        max_tokens=1024,                       # room for a short label plus any brief thinking
        output_config={"effort": "low"},       # a simple task: think little, answer fast
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            # The message content is a list of blocks; Claude reads them in order.
            "content": [
                {
                    "type": "text",
                    "text": f"<document>\n{document_markdown}\n</document>",
                    # cache_control marks the END of the part to cache: everything up to here
                    # (system prompt + this document) is stored and reused by the next calls.
                    "cache_control": {"type": "ephemeral"},   # "ephemeral" = kept for 5 minutes
                },
                {
                    "type": "text",
                    "text": f"<chunk>\n{chunk_for_prompt(chunk)}\n</chunk>\n\nWrite the label for this chunk.",
                },
            ],
        }],
    )

    # stop_reason says why Claude stopped. "refusal" = it declined (very unlikely for hotel text);
    # "max_tokens" = it ran out of room. Either way there's no usable label.
    if response.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"No label for chunk {chunk.index} of {chunk.document}: stop_reason={response.stop_reason}")

    # response.content is a list of blocks, e.g. [ThinkingBlock(...), TextBlock(text="Spa price list – ...")].
    # The label is the text block; thinking blocks (if any) are skipped.
    label = " ".join(block.text for block in response.content if block.type == "text").strip()
    label = " ".join(label.split())            # one line: collapse any newlines / double spaces
    if not label:
        raise RuntimeError(f"Empty label for chunk {chunk.index} of {chunk.document}")

    usage = LabelUsage(
        cache_write=response.usage.cache_creation_input_tokens or 0,
        cache_read=response.usage.cache_read_input_tokens or 0,
        uncached_input=response.usage.input_tokens,
        output=response.usage.output_tokens,
    )
    return label, usage


def label_chunks(
    client: anthropic.Anthropic, document_markdown: str, chunks: list[Chunk]
) -> tuple[list[Chunk], list[LabelUsage]]:
    """
    Label every chunk of ONE document (one call per chunk, same document each time -> cache reuse).

    Shape returned: (labelled chunks, usage per call), in the same order as `chunks`
        ([Chunk(document="overlook_spa_price_list.pdf", index=0, ..., label="Spa price list – opening hours ..."),
          Chunk(document="overlook_spa_price_list.pdf", index=1, ..., label="Spa price list – access to spa facilities ..."),
          ...],
         [LabelUsage(cache_write=812, cache_read=0, ...), LabelUsage(cache_write=0, cache_read=812, ...), ...])
    """
    labelled: list[Chunk] = []
    usages: list[LabelUsage] = []
    for chunk in chunks:
        label, usage = write_label(client, document_markdown, chunk)
        # replace(...) makes a COPY of the chunk with `label` filled in (the original stays unchanged).
        labelled.append(replace(chunk, label=label))
        usages.append(usage)
    return labelled, usages
