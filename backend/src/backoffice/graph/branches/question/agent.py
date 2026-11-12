"""The question agent (step 12): the ONE place in the project where the model decides what happens next.

=================================================================================================
IN ARIN'S WORDS: how the agent loop works
=================================================================================================
- agent does NOT perform the search. agent basically asks the LLM: "do you have all you need to
  answer the question?"
- The LLM replies with ONE of its two tools:
    search_documents   "no, we need to run the search documents tool" (with the words to search for)
    give_final_answer  "yes, this is the answer" (the answer form: status, answer, sources ...)
- The final answer is ALSO a tool call (give_final_answer). That's why a reply with NO tool call at
  all is an error: it means the LLM ignored its instructions.
- The first reply is normally search_documents: the LLM has found nothing yet. If it ever answered
  straight away, the answer would cite no chunk a search returned, and the answer check (12.2)
  would hold it back and send it to the front desk.
- So agent always returns the messages, plus one of two things:
    the LLM asked to search  -> pending_search = {"id": ..., "query": "..."}  (the search to run)
    the LLM gave its answer  -> pending_search = None, and question_answer = the answer form
- If search_documents is what the LLM returns, then we run search_step. search_step performs the
  search (run_search_tool: Voyage + pgvector + reranker) and adds the results to the messages.
- After search_step there is ALWAYS another agent call (a fixed arrow, no check in between), so the
  LLM can look at the new results and decide again: search more, or answer.
- after_agent (the routing decision) runs ONLY right after agent, never right after search_step. It
  reads pending_search, which agent has JUST written: a search -> "search_step"; None ->
  "check_agent_answer". (search_step also sets pending_search to None, but agent runs next and
  overwrites it before after_agent reads it.)
- What ends the loop: the turn in which the LLM calls give_final_answer, so agent writes
  pending_search = None.

Real run of #7, pending_search after every node:
    agent        -> pending_search = {"query": "children unaccompanied pool age rules"}  -> after_agent: "search_step"
    search_step  -> pending_search = None   (never read: agent runs next)
    agent        -> pending_search = {"query": "hedge maze opening hours August"}       -> after_agent: "search_step"
    search_step  -> pending_search = None   (never read)
    agent        -> pending_search = None   (the LLM called give_final_answer)          -> after_agent: "check_agent_answer"

The same loop in plain Python, without LangGraph (the shape of a hand-written RAG agent):
    messages = [{"role": "user", "content": email}]
    while True:
        response = ask_claude(messages, tools=[search_documents, give_final_answer])   # = the agent node
        messages.append(<Claude's turn>)
        call = <the tool call in response>
        if call.name == "search_documents" and searches < 4:                          # = after_agent -> "search_step"
            results = run_search_tool(call.input["query"])                            # = the search_step node
            messages.append(<tool_result with the results, same id as the call>)
            continue                                                                  # = the arrow back to agent
        answer = call.input                                                           # = after_agent -> "check_agent_answer"
        break
LangGraph just splits that while-loop into boxes and arrows, so every turn is saved by the
checkpointer, traced in Langfuse, and shown as a step in the UI.

THE GENERAL RULE (any tool-using agent in LangGraph, the "ReAct loop"): an LLM node + a tools node,
a conditional edge after the LLM node ("did it call a tool?" -> tools node, else finish), and a
fixed edge tools node -> LLM node. More tools don't add nodes: the tools node just looks the tool up
by name. LangGraph ships this ready-made (ToolNode, tools_condition, create_react_agent) for
LangChain models; we call Claude through the Anthropic SDK directly (decided in step 8), so the two
nodes are written by hand. Our one extra: we finish with a give_final_answer tool instead of plain
text, so the answer comes back structured (status, sources) for the code checks.

=================================================================================================

    agent ──(LLM called search_documents)──► search_step ──┐
      ▲                                                    │
      └──────────────── always back to agent ──────────────┘
      │
      └──(LLM called give_final_answer)──► check_agent_answer (12.2) ──► a reply

Why this is an agent and the other branches aren't: in booking and invoice CODE decides the next
step; here the MODEL decides whether to search again or answer, because nobody knows in advance
how many searches a question needs (#6 two topics, #7 two topics, #8 searches and finds nothing).
Code still sets the limits: at most MAX_SEARCHES searches, one tool call per turn.

=================================================================================================
HOW A TOOL CALL TRAVELS (Anthropic Messages API), with #7
=================================================================================================
state["agent_messages"] is the whole conversation, re-sent to the model every turn (the API keeps
no memory between calls). After one search it looks like:
    [{"role": "user", "content": "<email>From: Daniel Reyes ... </email>"},
     {"role": "assistant", "content": [                                    <- the model's turn, as it came back
         {"type": "thinking", "thinking": "", "signature": "..."},          (Haiku 5.5 always thinks first)
         {"type": "tool_use", "id": "toolu_01A...", "name": "search_documents",
          "input": {"query": "indoor pool age rule children"}}]},
     {"role": "user", "content": [                                         <- our answer to its tool call
         {"type": "tool_result", "tool_use_id": "toolu_01A...",
          "content": "[chunk 12] overlook_house_rules.docx > 9. Children, relevance 0.64\n..."}]}]
The tool_use "id" and the tool_result "tool_use_id" must match: that's how the model knows which
call the result answers.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
from pathlib import Path                       # Path: a file path you can join with /

# Langfuse (tracing):
from langfuse import observe                   # @observe: record this function as a named step in the trace

# OURS:
from backoffice.graph.state import EmailState, ParsedEmail, QuestionAnswer
from backoffice.llm import anthropic_client                        # the shared Claude client
from backoffice.tools.search_documents import SEARCH_TOOL, format_results_for_llm, run_search_tool
from backoffice.tracing import init_tracing

init_tracing()     # the Langfuse client must exist before the first @observe call (see tracing.py)

# Claude Haiku 5.5 first (Arin's leaning, decided 2026-11-12); switch only this line if the real
# runs (3 per email) show it misjudging "not found" or adding facts.
AGENT_MODEL = "claude-haiku-5-5"

# Code's limit on the loop: the model can't search forever. After this many searches, a further
# search request is answered with "limit reached, give your final answer" instead of results.
MAX_SEARCHES = 4

# agent.py is at backoffice/graph/branches/question/ -> three levels up is backoffice/.
SYSTEM_PROMPT = (Path(__file__).resolve().parents[3] / "prompts" / "question_agent_system.md").read_text(encoding="utf-8")

# The agent's second tool: how it FINISHES. Its input schema is the QuestionAnswer form
# (graph/state.py), so the final answer arrives already structured; strict: True makes the API
# guarantee the input matches the schema.
ANSWER_TOOL = {
    "name": "give_final_answer",
    "description": "Give your final answer to the guest's email. Call this once, when you have searched enough.",
    "input_schema": QuestionAnswer.model_json_schema(),
    "strict": True,
}


def build_prompt(email: ParsedEmail) -> str:
    """
    The first message of the conversation: the guest's email, between <email> tags (data, never
    instructions).
        <email>
        From: Daniel Reyes <d.reyes@mail.example>
        Subject: Kids question for our August trip

        Hi! We're coming in August with our son, who is 10. Can he use the indoor pool ...
        </email>
    """
    return f"<email>\nFrom: {email.sender}\nSubject: {email.subject}\n\n{email.body}\n</email>"


@observe(name="ask_llm_to_decide_next_step", capture_input=False)
def ask_llm_to_decide_next_step(messages: list[dict]):
    """
    One call to Claude with both tools: it answers with exactly one tool call.

    tool_choice={"type": "auto", "disable_parallel_tool_use": True}:
      "auto"   the model decides whether and which tool to call (forcing a tool isn't used: the
               prompt says every reply must be a tool call, and code checks it below);
      disable_parallel_tool_use  at most ONE tool call per turn, so every search is its own
               visible step (and one tool_result per turn).
    """
    response = anthropic_client().messages.create(
        model=AGENT_MODEL,
        max_tokens=8192,
        output_config={"effort": "medium"},       # Haiku 5.5's default, written out: judging "found or not" needs some thought
        system=SYSTEM_PROMPT,
        tools=[SEARCH_TOOL, ANSWER_TOOL],
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        messages=messages,
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"Question agent stopped: stop_reason={response.stop_reason}")
    return response


def agent(state: EmailState) -> dict:
    """
    THE AGENT NODE: one model turn. It does NOT search: it asks the LLM "do you have all you need
    to answer?". Returns the messages + either a search to run (pending_search) or the final answer
    (pending_search = None + question_answer). See "IN ARIN'S WORDS" at the top of this file.

    Examples (#7):
        1st turn -> {"agent_messages": [...], "pending_search": {"id": "toolu_01A...", "query": "indoor pool age rule children"}}
        3rd turn -> {"agent_messages": [...], "pending_search": None,
                     "question_answer": QuestionAnswer(status="answered", answer="...", sources=[12, 7], ...)}
    """
    messages = list(state.get("agent_messages") or [{"role": "user", "content": build_prompt(state["email"])}])
    response = ask_llm_to_decide_next_step(messages)

    # Keep the model's whole turn, unchanged (thinking blocks included: the API requires them back
    # as they came). model_dump (Pydantic) turns each SDK block object into a plain dict, so the
    # conversation can be saved by the checkpointer.
    messages.append({"role": "assistant",
                     "content": [block.model_dump(mode="json", exclude_none=True) for block in response.content]})

    tool_calls = [block for block in response.content if block.type == "tool_use"]
    if not tool_calls:
        # The prompt says every reply is a tool call. Step 13 will turn this into "send to a human".
        raise RuntimeError("Question agent replied without calling a tool")
    call = tool_calls[0]                       # at most one (disable_parallel_tool_use)

    if call.name == "search_documents":
        return {"agent_messages": messages, "pending_search": {"id": call.id, "query": call.input["query"]}}

    # give_final_answer: model_validate (Pydantic) checks the input against QuestionAnswer and
    # builds the object.
    return {"agent_messages": messages, "pending_search": None,
            "question_answer": QuestionAnswer.model_validate(call.input)}


def search_step(state: EmailState) -> dict:
    """
    THE SEARCH NODE (code): run the search the agent asked for and give it the results. After this
    node there is ALWAYS another agent call (the fixed arrow in subgraph.py), so the LLM can decide
    again with the new results. It sets pending_search back to None, but that None is never read:
    agent runs next and overwrites it.

    Example (#7, 2nd search):
        in:  pending_search = {"id": "toolu_01B...", "query": "hedge maze opening months"}
        out: {"searches": [<1st search>, SearchRecord(query="hedge maze opening months", results=[... 4 ...])],
              "agent_messages": [..., {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01B...",
                                                                    "content": "[chunk 7] ... Hedge maze ..."}]}],
              "pending_search": None}
    """
    pending = state["pending_search"]
    searches = list(state.get("searches", []))

    if len(searches) >= MAX_SEARCHES:
        text = f"Search limit reached ({MAX_SEARCHES} searches). Give your final answer now with what you found."
    else:
        record = run_search_tool(pending["query"])
        searches.append(record)
        text = format_results_for_llm(record.results)
        if len(searches) == MAX_SEARCHES:
            text += f"\n\n(That was your last search: {MAX_SEARCHES} of {MAX_SEARCHES}. Next, give your final answer.)"

    tool_result = {"type": "tool_result", "tool_use_id": pending["id"], "content": text}
    return {"agent_messages": state["agent_messages"] + [{"role": "user", "content": [tool_result]}],
            "searches": searches,
            "pending_search": None}


def after_agent(state: EmailState) -> str:
    """
    The routing decision after each agent turn (code). Returns the NAME of the next node.

    It reads state["pending_search"], which the agent node has JUST written:
      - a search, e.g. {"id": "toolu_01B...", "query": "hedge maze opening hours"}
        (Claude called search_documents)                           -> "search_step"
      - None (Claude called give_final_answer)                     -> "check_agent_answer"

    It never runs after search_step: the arrow from search_step goes straight back to agent, which
    writes pending_search again before this function reads it.
    """
    return "search_step" if state.get("pending_search") else "check_agent_answer"
