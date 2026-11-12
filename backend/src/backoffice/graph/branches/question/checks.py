"""Question branch: check the agent's answer (CODE only), and the routing decision (step 12.2).

In:   state["question_answer"]  the agent's final answer;  state["searches"]  every search it made
Out:  {"answer_check": AnswerCheck(outcome=SEND_ANSWER / NOT_FOUND / FAILED_CHECK, problems=[...])}

The node only gathers the inputs; the rules live in services/answer_check.py (tested on their own).
"""

# --- Where every name used in this file comes from ------------------------------------------------
# OURS:
from backoffice.graph.state import EmailState
from backoffice.services.answer_check import AnswerOutcome, check_answer


def retrieved_chunks(state: EmailState) -> dict[int, str]:
    """
    Every chunk the agent's searches returned in this run, chunk id -> text.

    Shape (#7, 3 searches, overlapping results counted once):
        {20: "9. Children. Children under 14 must be accompanied by an adult ...",
         4: "Indoor pool. Our heated indoor pool is open daily from 7:00 AM to 10:00 PM ...",
         9: "Hedge maze. Our hedge maze in the east gardens is open from June to September ...",
         ...}
    The double "for" (plain Python) walks every result of every search.
    """
    return {r.chunk_id: r.text for search in state.get("searches", []) for r in search.results}


def check_agent_answer(state: EmailState) -> dict:
    """
    THE NODE: run the code checks on the agent's answer.
        #6 -> {"answer_check": AnswerCheck(outcome=SEND_ANSWER, problems=[])}
        #8 -> {"answer_check": AnswerCheck(outcome=NOT_FOUND, problems=[])}
    """
    answer = state["question_answer"]
    return {"answer_check": check_answer(answer.status, answer.answer, answer.sources, retrieved_chunks(state))}


# The reply node for each outcome (replies.py).
REPLY_FOR_OUTCOME = {
    AnswerOutcome.SEND_ANSWER: "answer_reply",
    AnswerOutcome.NOT_FOUND: "not_found_note",
    AnswerOutcome.FAILED_CHECK: "check_failed_note",
}


def after_answer_check(state: EmailState) -> str:
    """The routing decision (code): #6, #7 -> "answer_reply";  #8 -> "not_found_note"."""
    return REPLY_FOR_OUTCOME[state["answer_check"].outcome]
