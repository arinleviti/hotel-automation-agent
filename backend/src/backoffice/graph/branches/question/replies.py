"""Question branch, the REPLY nodes (step 12.2).

    outcome (checks.py)   node                template                     goes to           kind
    SEND_ANSWER           answer_reply        question_answer.txt          the guest         reply_to_sender   #6, #7
    NOT_FOUND             not_found_note      question_not_found.txt       the front desk    forward_to_staff  #8
    FAILED_CHECK          check_failed_note   question_check_failed.txt    the front desk    forward_to_staff

The ONE difference from booking and invoice: in answer_reply the middle of the email ($answer) is
text the LLM WROTE (questions are open-ended). It has passed the code checks (sources real, no
invented amounts) and still goes through the human approval like every draft. The greeting and
signature are fixed text from the template. How a template is filled: graph/branches/templates.py.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# OURS:
from backoffice.graph.branches.human_review import FRONT_DESK      # "Front desk <frontdesk@overlook-hotel.example>"
from backoffice.graph.branches.templates import bullet_list, render, reply_subject
from backoffice.graph.state import DraftKind, EmailState, OutgoingDraft, SearchRecord
from backoffice.services.booking_request import greeting_name      # signature name -> From name -> "guest"


def summarize_searches(searches: list[SearchRecord]) -> str:
    """
    Every search and what it found, for the front desk (and the evidence view in 12.3).

    Example (#8):
          - "helicopter transfer from Denver airport": Getting here 0.41, House Rules & Policies > 7. Transportation 0.34, ...
          - "helicopter": House Rules & Policies > 7. Transportation 0.36, Getting here 0.34, ...
    """
    lines = []
    for search in searches:
        found = ", ".join(f"{' > '.join(r.headings) or r.document} {r.rerank_score:.2f}" for r in search.results)
        lines.append(f'"{search.query}": {found or "nothing"}')
    return bullet_list(lines)


def question_evidence(state: EmailState) -> dict:
    """
    For the approval screen (step 12.3): every search the agent made and what it found, the sources
    its answer cites, what isn't in the documents, and the code check. "Every claim shows its
    evidence" (CLAUDE.md, core principles). Used by nodes/approval.py.

    Shape returned (#7):
        {"searches": ['"children unaccompanied pool age rules": 9. Children 0.79, Indoor pool 0.70, ...',
                      '"hedge maze opening hours August": Hedge maze 0.80, ...'],
         "sources": ["[4] overlook_guest_information.pdf > Indoor pool (page 1)",
                     "[20] overlook_house_rules.docx > House Rules & Policies > 9. Children",
                     "[9] overlook_guest_information.pdf > Hedge maze (page 2)"],
         "not_in_documents": ["Whether a 10-year-old may enter the hedge maze without an adult"],
         "check": "send_answer"}
    """
    searches = state.get("searches", [])
    answer, check = state["question_answer"], state["answer_check"]
    # Every chunk retrieved in this run, by id, to describe the cited ones.
    chunks = {r.chunk_id: r for search in searches for r in search.results}
    sources = []
    for chunk_id in answer.sources:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            sources.append(f"[{chunk_id}] (never retrieved!)")
            continue
        pages = f" (page {', '.join(map(str, chunk.pages))})" if chunk.pages else ""
        sources.append(f"[{chunk_id}] {chunk.document} > {' > '.join(chunk.headings)}{pages}")
    return {
        "searches": summarize_searches(searches).splitlines(),
        "sources": sources,
        "not_in_documents": answer.not_in_documents,
        "check": f"{check.outcome}" + (f": {'; '.join(check.problems)}" if check.problems else ""),
    }


def note_to_front_desk(state: EmailState, template: str, extra: dict[str, str], reason: str) -> dict:
    """The forward_to_staff draft shared by not_found_note and check_failed_note."""
    email = state["email"]
    values = {"sender": email.sender, "original_subject": email.subject, "original_body": email.body,
              "searches": summarize_searches(state.get("searches", []))} | extra
    # dict | dict (plain Python, 3.9+) = one dict with the keys of both.
    return {"outgoing_draft": OutgoingDraft(
        kind=DraftKind.FORWARD_TO_STAFF,
        outgoing_to=FRONT_DESK,
        outgoing_subject=f"Needs a person: {email.subject}",
        outgoing_body=render(template, values),
        reason=reason,
    )}


def answer_reply(state: EmailState) -> dict:
    """
    NODE (SEND_ANSWER): the agent's answer, inside the fixed greeting and signature, to the guest.
        to: "Daniel Reyes <d.reyes@mail.example>"   subject: "Re: Kids question for our August trip"
        body: "Dear Daniel Reyes,\\n\\nThank you for your email.\\n\\n<the agent's answer>\\n\\nKind regards, ..."
    """
    email, answer = state["email"], state["question_answer"]
    body = render("question_answer", {"guest_name": greeting_name(answer.guest_name, email.body, email.sender),
                                      "answer": answer.answer})
    searches = len(state.get("searches", []))
    return {"outgoing_draft": OutgoingDraft(
        kind=DraftKind.REPLY_TO_SENDER,
        outgoing_to=email.sender,
        outgoing_subject=reply_subject(email.subject),
        outgoing_body=body,
        reason=f"Answered from the hotel's documents after {searches} search(es); "
               f"sources: chunks {answer.sources}; code checks passed.",
    )}


def not_found_note(state: EmailState) -> dict:
    """NODE (NOT_FOUND): the documents don't cover the request: the front desk replies personally. (#8)"""
    answer = state["question_answer"]
    missing = answer.not_in_documents or ["(the agent found nothing relevant)"]
    return note_to_front_desk(state, "question_not_found", {"not_in_documents": bullet_list(missing)},
                              reason=f"Not in the documents: {'; '.join(missing)}.")


def check_failed_note(state: EmailState) -> dict:
    """NODE (FAILED_CHECK): the drafted answer broke a rule: held back, the front desk sees it and why."""
    answer, check = state["question_answer"], state["answer_check"]
    return note_to_front_desk(state, "question_check_failed",
                              {"problems": bullet_list(check.problems), "answer": answer.answer or "(empty)"},
                              reason=f"Drafted answer held back: {'; '.join(check.problems)}")
