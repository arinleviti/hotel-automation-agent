"""End-to-end tests of the question branch (the agent) INSIDE the real main graph (step 12.3).

    read_email -> classify -> decide_route -> question_branch (agent <-> search_step loop, checks,
    reply) -> approval (pause) -> resume -> action -> END

Faked, so no cost: classify (a fake Claude saying "question"), the agent (a SCRIPTED fake Claude
playing its turns), the search (hand-made results), and the action node's write (fake_actions_table).
"""

from types import SimpleNamespace

import pytest

import backoffice.graph.branches.question.agent as agent_module
import backoffice.graph.nodes.classify as classify_module
from backoffice.graph.main_graph import build_graph, process_email, resume_email
from backoffice.graph.state import Classification, SearchRecord
from backoffice.rag.search import SearchResult

QUESTION = Classification(type="question", suspicious=False, suspicious_reason="", confidence=0.95,
                          summary="Guest question.")

POOL = SearchResult(chunk_id=4, document="overlook_guest_information.pdf", headings=["Indoor pool"], pages=[1],
                    label="Guest information: indoor pool",
                    text="Indoor pool. Open daily from 7:00 AM to 10:00 PM. Free for hotel guests.",
                    vector_similarity=0.6, rerank_score=0.87)


class Block(SimpleNamespace):
    def model_dump(self, **kwargs):
        return dict(vars(self))


def tool_call(name, tool_input, call_id):
    return SimpleNamespace(stop_reason="tool_use",
                           content=[Block(type="tool_use", id=call_id, name=name, input=tool_input)],
                           usage=SimpleNamespace(input_tokens=900, output_tokens=60))


@pytest.fixture
def scripted_world(monkeypatch, fake_actions_table):
    """Fake classify + a scripted agent + a fake search; returns a function to install a script."""
    monkeypatch.setattr(classify_module, "anthropic_client", lambda: SimpleNamespace(messages=SimpleNamespace(
        parse=lambda **request: SimpleNamespace(stop_reason="end_turn", parsed_output=QUESTION,
                                                usage=SimpleNamespace(input_tokens=500, output_tokens=60)))))
    monkeypatch.setattr(agent_module, "run_search_tool", lambda query: SearchRecord(query=query, results=[POOL]))

    def install(script):
        turns = iter(script)
        monkeypatch.setattr(agent_module, "anthropic_client",
                            lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **request: next(turns))))
    return install


def test_an_answered_question_pauses_with_the_answer_and_its_evidence(scripted_world):
    scripted_world([
        tool_call("search_documents", {"query": "indoor pool"}, "toolu_1"),
        tool_call("give_final_answer", {"status": "answered", "answer": "Our indoor pool is open daily from 7:00 AM "
                                        "to 10:00 PM and is free for hotel guests.", "sources": [4],
                                        "not_in_documents": [], "guest_name": "Linda Okafor"}, "toolu_2"),
    ])

    result = process_email("06_question_pool_and_spa")

    assert result.nodes_run == ["read_email", "classify", "decide_route",
                                "question_branch > agent", "question_branch > search_step", "question_branch > agent",
                                "question_branch > check_agent_answer", "question_branch > answer_reply"]
    request = result.waiting_for_human
    assert request["evidence"]["searches"] == ['  - "indoor pool": Indoor pool 0.87']
    assert request["evidence"]["sources"] == ["[4] overlook_guest_information.pdf > Indoor pool (page 1)"]
    assert request["evidence"]["check"] == "send_answer"
    assert request["outgoing_draft"]["outgoing_body"].startswith("Dear Linda Okafor,")


def test_not_found_is_a_note_to_the_front_desk_and_approved_is_recorded(scripted_world, fake_actions_table):
    scripted_world([
        tool_call("search_documents", {"query": "helicopter transfer"}, "toolu_1"),
        tool_call("give_final_answer", {"status": "not_found", "answer": "", "sources": [],
                                        "not_in_documents": ["a helicopter transfer from DEN"],
                                        "guest_name": "Richard Hale"}, "toolu_2"),
    ])
    graph = build_graph()
    paused = process_email("08_question_helicopter_not_found", graph)
    assert paused.nodes_run[-1] == "question_branch > not_found_note"
    assert paused.waiting_for_human["outgoing_draft"]["kind"] == "forward_to_staff"

    resumed = resume_email(paused.thread_id, {"decision": "approve"}, graph)

    assert resumed.state["final_outgoing_message"].outgoing_subject == "Needs a person: Transfer from DEN"
    assert fake_actions_table[0]["email_name"] == "08_question_helicopter_not_found"
