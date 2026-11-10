"""Tests for rag/contextual_chunk_labels.py with a FAKE client: no request is sent, nothing is paid."""

from types import SimpleNamespace

import pytest

from backoffice.rag.chunking import Chunk
from backoffice.rag.contextual_chunk_labels import LABEL_MODEL, label_chunks, write_label

SPA_DOCUMENT = "## Treatments\n\n| Treatment | Duration | Price |\n| - | - | - |\n| Private sauna (up to 4 people) | 60 min | $90 |"
SAUNA_CHUNK = Chunk(document="overlook_spa_price_list.pdf", index=4, headings=["Treatments"],
                    text="| Treatment | Duration | Price |\n| - | - | - |\n| Private sauna (up to 4 people) | 60 min | $90 |",
                    pages=[1, 2])


class FakeClaude:
    """
    Stands in for anthropic.Anthropic: records every request and returns a canned answer.
    fake.messages.create(...) works like the real client.messages.create(...).

    Shape of a returned response (only the parts our code reads):
        SimpleNamespace(stop_reason="end_turn",
                        content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="...label...")],
                        usage=SimpleNamespace(cache_creation_input_tokens=0, cache_read_input_tokens=812,
                                              input_tokens=61, output_tokens=27))
    """

    def __init__(self, label_text: str = "Spa price list – Treatments: extras such as the private sauna.",
                 stop_reason: str = "end_turn"):
        self.requests: list[dict] = []
        self.label_text = label_text
        self.stop_reason = stop_reason
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=self.label_text)],
            usage=SimpleNamespace(cache_creation_input_tokens=0, cache_read_input_tokens=812,
                                  input_tokens=61, output_tokens=27),
        )


def test_request_uses_haiku_and_caches_the_document():
    fake = FakeClaude()

    write_label(fake, SPA_DOCUMENT, SAUNA_CHUNK)

    request = fake.requests[0]
    document_block, chunk_block = request["messages"][0]["content"]
    assert request["model"] == LABEL_MODEL == "claude-haiku-5-5"
    assert SPA_DOCUMENT in document_block["text"]
    assert document_block["cache_control"] == {"type": "ephemeral"}       # the document is the cached part
    assert "cache_control" not in chunk_block                             # the chunk changes every call
    assert "Headings: Treatments" in chunk_block["text"]
    assert "Private sauna" in chunk_block["text"]


def test_label_is_the_text_block_on_one_line():
    fake = FakeClaude(label_text="  Spa price list –\nTreatments:   extras.  ")

    label, usage = write_label(fake, SPA_DOCUMENT, SAUNA_CHUNK)

    assert label == "Spa price list – Treatments: extras."                # thinking block skipped, spaces/newlines collapsed
    assert usage.cache_read == 812


def test_refusal_raises_instead_of_returning_a_label():
    with pytest.raises(RuntimeError, match="refusal"):
        write_label(FakeClaude(stop_reason="refusal"), SPA_DOCUMENT, SAUNA_CHUNK)


def test_label_chunks_fills_the_label_and_keeps_the_text():
    fake = FakeClaude()
    other = Chunk(document="overlook_spa_price_list.pdf", index=0, headings=["Spa & Wellness Price List 2026"],
                  text="Open daily from 9:00 AM to 8:00 PM.", pages=[1])

    labelled, usages = label_chunks(fake, SPA_DOCUMENT, [other, SAUNA_CHUNK])

    assert len(fake.requests) == 2                                        # one call per chunk
    assert all(c.label for c in labelled)
    assert labelled[1].text == SAUNA_CHUNK.text                           # the text is never changed
    assert SAUNA_CHUNK.label == ""                                        # the original chunk is untouched (copy made)
    assert len(usages) == 2
