"""Langfuse tracing: a recording of what happened when one email went through the graph.

=================================================================================================
WHAT YOU GET
=================================================================================================
Every time an email runs through the graph, Langfuse (the website you have an account on) gets
one "trace": a list of the steps that ran, with what went in and what came out of each one.
Real trace of email #9, as Langfuse shows it:

    LangGraph                          <- the whole run
      read_email                       <- node 1: in = the file path, out = the parsed email
      classify                         <- node 2
        classify_email                 <- our function inside node 2
          anthropic.messages.create    <- the call to Claude: the prompt, Claude's answer,
                                          model=claude-haiku-5-5, 1478 + 139 tokens, $0.000217
      decide_route                     <- node 3: out = {"route": "human", "reason_for_human_review": ...}
        follow_route
      human_review                     <- the branch it went to

=================================================================================================
HOW EACH LINE GETS THERE (three different ways)
=================================================================================================

1) The graph's nodes (read_email, classify, decide_route, human_review): a CALLBACK.

   A callback is an object you hand to someone else, so that THEY call it back when something
   happens. Here we hand Langfuse's CallbackHandler to LangGraph:

       graph.invoke(starting_state, config={"callbacks": [CallbackHandler()]})

   OUR code only does the handing over: that one config={"callbacks": ...} argument, in
   main_graph.py (run_config, used by process_email and resume_email). Nothing else.

   Everything else happens INSIDE THE INSTALLED LIBRARIES (in backend/.venv, not in our project):
     - LangGraph, while running the graph, calls the handler's methods at every node:
       on_chain_start(...) when a node starts, on_chain_end(...) when it finishes.
       (The calling side lives in .venv/Lib/site-packages/langchain_core/callbacks/manager.py.)
     - Those methods are written by Langfuse, inside the CallbackHandler class, and they send
       each start/finish to Langfuse.
       (.venv/Lib/site-packages/langfuse/langchain/CallbackHandler.py, def on_chain_start / on_chain_end.)

   So the sequence, for each node, is:
       LangGraph: "read_email is starting"  ->  handler.on_chain_start(...)  ->  sent to Langfuse
       LangGraph runs read_email
       LangGraph: "read_email finished"     ->  handler.on_chain_end(...)    ->  sent to Langfuse
   That's why every node appears in the trace without us writing anything in the nodes.

2) The call to Claude (anthropic.messages.create): AUTOMATIC, nothing to write.

   The Anthropic library has tracing built in: every time it calls Claude, it reports the call
   (model, prompt, answer, tokens) in OpenTelemetry format, a standard format for traces that
   many tools understand. Langfuse listens for those reports and adds them to the trace.
   (This is a recent feature. With older versions you had to wrap the Claude call yourself:
   that's the "wrap the LLM call" pattern you may remember from your previous project.)

3) Our own functions (classify_email, search_documents): the @observe DECORATOR.

   This IS the "wrap a function" pattern. Writing @observe(...) on the line above a function
   wraps it: every call to the function is recorded as a step in the trace, with its result.

       @observe(name="classify_email")
       def classify_email(email): ...

   means the same as writing, by hand:

       def classify_email(email): ...
       classify_email = observe(name="classify_email")(classify_email)   # replace it with a wrapped version

   and the wrapped version does, roughly:
       record "classify_email started"  ->  run the real classify_email  ->  record "finished, returned X"

   We use it for functions we want to see by name in the trace, and for the Voyage calls in
   search_documents (Voyage, unlike Anthropic, doesn't report its calls by itself).

=================================================================================================
WHERE OUR CODE USES LANGFUSE, in the order it happens when you run one email
=================================================================================================
We use 5 things from the langfuse library:
    from langfuse import Langfuse, observe, propagate_attributes
    from langfuse.langchain import CallbackHandler
    ... and the client's .flush()

 1. Python IMPORTS our files (before anything runs):
      nodes/classify.py and rag/search.py call init_tracing() at the top
        -> Langfuse(public_key=..., secret_key=..., base_url=...)   FIRST Langfuse call: the client
      and @observe(...) wraps classify_email and search_documents (it just prepares the wrapper)
 2. process_email(name)   (main_graph.py)
      with propagate_attributes(trace_name="email <name>", session_id=thread_id, ...):
                                                                   "everything inside belongs to
                                                                   ONE trace, called email <name>"
 3.   graph.stream(..., config=run_config(thread_id))   run_config includes "callbacks": graph_callbacks()
        graph_callbacks() -> [CallbackHandler(...)]                the handler, given to LangGraph
        while the graph runs:
          - each node starting/finishing  -> LangGraph tells the CallbackHandler  -> sent
          - classify_email runs           -> the @observe wrapper records it      -> sent
          - the Claude call               -> recorded by the Langfuse client automatically
                                             (it receives the Anthropic library's OpenTelemetry reports)
 4. at the end: flush_traces() -> client.flush()   send whatever is still waiting

=================================================================================================
WHY THIS FILE EXISTS
=================================================================================================
Langfuse's library looks for its keys in ENVIRONMENT variables. Ours are in the .env file, which
only our settings (config.py) read. So we create the Langfuse client ourselves, with the keys
from our settings (init_tracing), and give the graph its callback (graph_callbacks).
"""

from functools import lru_cache

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from backoffice.config import get_settings


@lru_cache(maxsize=1)
def init_tracing() -> Langfuse:
    """
    Create the Langfuse client: the object that sends recordings to the Langfuse website.

    Created ONCE (lru_cache: later calls return the same one). Once it exists, @observe and the
    automatic Claude recording send to it. If tracing is switched off (TRACING_ENABLED=false, as in
    the tests) or the keys are missing, it is created switched off: the code runs, nothing is sent.
    """
    settings = get_settings()
    has_keys = settings.langfuse_public_key is not None and settings.langfuse_secret_key is not None
    enabled = settings.tracing_enabled and has_keys
    return Langfuse(
        public_key=settings.langfuse_public_key if enabled else "tracing-disabled",
        secret_key=settings.langfuse_secret_key.get_secret_value() if enabled else "tracing-disabled",
        base_url=settings.langfuse_base_url,
        tracing_enabled=enabled,
    )


def graph_callbacks() -> list[CallbackHandler]:
    """
    The callback to hand to LangGraph (way 1 above), so every node gets recorded.

    Used as:   graph.invoke(state, config={"callbacks": graph_callbacks()})
    Shape returned: [CallbackHandler(...)] when tracing is on, [] (no callback) when it is off.
    """
    init_tracing()                                    # the client must exist before the handler
    settings = get_settings()
    if not settings.tracing_enabled or settings.langfuse_public_key is None:
        return []
    # public_key says which Langfuse client (the one created in init_tracing) the handler sends to.
    return [CallbackHandler(public_key=settings.langfuse_public_key)]


def flush_traces() -> None:
    """
    Send any recordings still waiting. Langfuse doesn't send each step immediately: it collects
    them and sends them in batches, in the background. A short script must call this before it
    exits, otherwise the last steps would be lost when the program stops.
    """
    init_tracing().flush()
