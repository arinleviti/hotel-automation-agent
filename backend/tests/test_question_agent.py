"""Tests for the question agent loop (graph/branches/question/): a SCRIPTED fake Claude plays the
model's turns, and a fake search returns hand-made results. No cost, no database, no Voyage."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import backoffice.graph.branches.question.agent as agent_module
from backoffice.graph.branches.question.subgraph import build_question_graph
from backoffice.graph.state import ParsedEmail, QuestionAnswer, SearchRecord
from backoffice.rag.search import SearchResult

EMAIL = ParsedEmail(sender="Daniel Reyes <d.reyes@mail.example>", to="info@overlook-hotel.example",
                    subject="Kids question for our August trip", date=datetime(2026, 11, 4, tzinfo=timezone.utc),
                    body="Can my 10-year-old use the indoor pool and the hedge maze in August?")

FINAL = {"status": "answered", "answer": "Under 14s need an adult at the pool. The maze is open June to September.",
         "sources": [20, 9], "not_in_documents": ["an age limit for the hedge maze"], "guest_name": "Daniel Reyes"}


class Block(SimpleNamespace):
    """A fake SDK content block: attributes like the real one, plus model_dump()."""
    def model_dump(self, **kwargs):
        return dict(vars(self))


def tool_call(name: str, tool_input: dict, call_id: str) -> SimpleNamespace:
    """A fake model response whose only content is one tool call."""
    return SimpleNamespace(stop_reason="tool_use",
                           content=[Block(type="tool_use", id=call_id, name=name, input=tool_input)],
                           usage=SimpleNamespace(input_tokens=900, output_tokens=60))


def fake_search(query: str) -> SearchRecord:
    result = SearchResult(chunk_id=20, document="overlook_house_rules.docx", headings=["9. Children"], pages=[],
                          label="House rules: children", text="Children under 14 must be accompanied by an adult.",
                          vector_similarity=0.5, rerank_score=0.81)
    return SearchRecord(query=query, results=[result])


@pytest.fixture
def scripted_model(monkeypatch):
    """
    Install a fake Claude that plays `script` (a list of responses) one turn at a time, and record
    the messages it was sent each turn.
    """
    sent: list[list[dict]] = []

    def install(script: list):
        turns = iter(script)

        def create(**request):
            sent.append([dict(m) for m in request["messages"]])
            return next(turns)

        monkeypatch.setattr(agent_module, "anthropic_client",
                            lambda: SimpleNamespace(messages=SimpleNamespace(create=create)))
        monkeypatch.setattr(agent_module, "run_search_tool", fake_search)
        return sent

    return install


def test_two_searches_then_an_answer(scripted_model):
    sent = scripted_model([
        tool_call("search_documents", {"query": "pool age rule children"}, "toolu_1"),
        tool_call("search_documents", {"query": "hedge maze opening months"}, "toolu_2"),
        tool_call("give_final_answer", FINAL, "toolu_3"),
    ])

    state = build_question_graph().invoke({"email": EMAIL})

    assert [s.query for s in state["searches"]] == ["pool age rule children", "hedge maze opening months"]
    assert state["question_answer"] == QuestionAnswer(**FINAL)
    # The 3rd turn saw: the email, turn 1, its result, turn 2, its result.
    third_turn = sent[2]
    assert [m["role"] for m in third_turn] == ["user", "assistant", "user", "assistant", "user"]
    result = third_turn[2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1"     # ids match
    assert "[chunk 20] overlook_house_rules.docx > 9. Children, relevance 0.81" in result["content"]


def test_code_stops_the_searching_after_the_limit(scripted_model):
    limit = agent_module.MAX_SEARCHES
    script = [tool_call("search_documents", {"query": f"try {n}"}, f"toolu_{n}") for n in range(limit + 1)]
    sent = scripted_model(script + [tool_call("give_final_answer", FINAL, "toolu_last")])

    state = build_question_graph().invoke({"email": EMAIL})

    assert len(state["searches"]) == limit                     # the extra request ran no search
    refused = sent[-1][-1]["content"][0]["content"]
    assert refused.startswith(f"Search limit reached ({limit} searches)")


def test_a_reply_without_a_tool_call_goes_to_a_person(scripted_model):
    # The agent node raises; since step 13 the subgraph's error handler catches it (no retry: it's
    # not a temporary problem) and writes a note to the front desk instead of crashing the run.
    scripted_model([SimpleNamespace(stop_reason="end_turn", content=[Block(type="text", text="The pool is open.")],
                                    usage=SimpleNamespace(input_tokens=900, output_tokens=20))])

    state = build_question_graph().invoke({"email": EMAIL})

    assert state["processing_error"]["step"] == "question_branch > agent"
    assert "without calling a tool" in state["processing_error"]["error"]
    assert state["outgoing_draft"].kind == "forward_to_staff"


def test_a_checked_answer_becomes_a_reply_to_the_guest(scripted_model):
    scripted_model([
        tool_call("search_documents", {"query": "pool age rule children"}, "toolu_1"),
        tool_call("give_final_answer", {**FINAL, "answer": "Children under 14 must be accompanied by an adult.",
                                        "sources": [20]}, "toolu_2"),
    ])

    state = build_question_graph().invoke({"email": EMAIL})

    draft = state["outgoing_draft"]
    assert draft.kind == "reply_to_sender" and draft.outgoing_to == EMAIL.sender
    assert draft.outgoing_subject == "Re: Kids question for our August trip"
    assert draft.outgoing_body.startswith("Dear Daniel Reyes,\n\nThank you for your email.\n\n"
                                          "Children under 14 must be accompanied by an adult.")


def test_not_found_becomes_a_note_to_the_front_desk(scripted_model):
    scripted_model([
        tool_call("search_documents", {"query": "helicopter transfer"}, "toolu_1"),
        tool_call("give_final_answer", {"status": "not_found", "answer": "", "sources": [],
                                        "not_in_documents": ["a helicopter transfer from DEN"],
                                        "guest_name": "Richard Hale"}, "toolu_2"),
    ])

    draft = build_question_graph().invoke({"email": EMAIL})["outgoing_draft"]

    assert draft.kind == "forward_to_staff" and draft.outgoing_to.startswith("Front desk")
    assert "  - a helicopter transfer from DEN" in draft.outgoing_body
    assert '  - "helicopter transfer": 9. Children 0.81' in draft.outgoing_body     # what the search found


def test_an_answer_with_an_invented_price_is_held_back(scripted_model):
    scripted_model([
        tool_call("search_documents", {"query": "pool"}, "toolu_1"),
        tool_call("give_final_answer", {**FINAL, "answer": "The pool costs $20 for children.", "sources": [20]}, "toolu_2"),
    ])

    state = build_question_graph().invoke({"email": EMAIL})

    assert state["answer_check"].outcome == "failed_check"
    draft = state["outgoing_draft"]
    assert draft.kind == "forward_to_staff"                       # never to the guest
    assert "The answer mentions $20, which is not in any cited passage." in draft.outgoing_body


def test_the_answer_tool_takes_exactly_the_question_answer_form():
    schema = agent_module.ANSWER_TOOL["input_schema"]
    assert agent_module.ANSWER_TOOL["strict"] is True
    assert schema["additionalProperties"] is False             # required by strict mode
    assert set(schema["required"]) == {"status", "answer", "sources", "not_in_documents", "guest_name"}
