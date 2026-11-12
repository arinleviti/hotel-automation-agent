"""The checkpointer: where LangGraph SAVES the state of a run, so a paused run can be resumed.

Why it's needed: the approval node pauses the run with interrupt() (see nodes/approval.py). The
run then stops completely; the staff member may answer minutes or days later. LangGraph saves the
state after EVERY node into the checkpointer, under the run's thread_id, and on resume reads it
back from there.

Two kinds, same job, different place:
    memory_checkpointer()      the saved states live in a Python dict INSIDE the running program.
                               Lost when the program ends. Used by the tests (fast, no database).
    postgres_checkpointer()    the saved states live in POSTGRES (step 9.3). A paused run survives
                               the program ending or restarting, and ANOTHER program can resume it.
                               Used by the command line now, by the backend API from step 15.
The graph doesn't care which one it gets: build_graph(checkpointer) takes either.

What's saved, roughly (per run, i.e. per thread_id), whichever kind:
    thread "6b9a9f43-...":
        checkpoint after read_email    {"email_path": ..., "email": ParsedEmail(...)}
        checkpoint after classify      {... + "classification": Classification(...)}
        ...
        checkpoint after human_review  {... + "outgoing_draft": OutgoingDraft(...)}  + "waiting at approval"
In Postgres these go into LangGraph's OWN tables (checkpoints, checkpoint_blobs, checkpoint_writes,
checkpoint_migrations), created by setup_checkpoint_tables(). Our code never reads those tables
directly: only LangGraph does. Our own record of the outcome is the `actions` table (action node).

=================================================================================================
WHY WE LIST OUR CLASSES (allowed_msgpack_modules)
=================================================================================================
The state contains our own objects: ParsedEmail, Classification, OutgoingDraft ... To save them,
LangGraph's serializer (JsonPlusSerializer: turns Python objects into bytes and back, using the
msgpack format) writes each object's class name next to its data, e.g.
    ("backoffice.graph.state", "OutgoingDraft") + {"kind": "forward_to_staff", ...}
and, when loading, creates an object of that class again.

Loading "whatever class the saved bytes name" is a security risk: if someone could write into the
checkpoint tables, they could make our program create objects of ANY class it can import. So
LangGraph lets us list the classes it may create; anything else is refused. Without a list it
allows everything and prints a warning ("Deserializing unregistered type ... will be blocked in
a future version"). We give the list explicitly: the types of EmailState, and nothing else.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
from collections.abc import Iterator                         # the return type of a generator (see below)
from contextlib import contextmanager                        # turns a function into a `with` block

# psycopg (the Postgres driver):
import psycopg                                               # psycopg.connect(...): open a connection
from psycopg.rows import dict_row                            # make rows come back as dicts (LangGraph needs it)

# LangGraph:
from langgraph.checkpoint.memory import InMemorySaver               # checkpointer in a Python dict
from langgraph.checkpoint.postgres import PostgresSaver             # checkpointer in Postgres (langgraph-checkpoint-postgres)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # objects <-> bytes

# OURS:
from backoffice.config import get_settings                   # DATABASE_URL from .env

# Every class of ours that can appear in EmailState (see graph/state.py), as (module, class name).
# Add a line here when a later step puts a new type into the state; otherwise loading it fails.
#   (final_outgoing_message, added in 9.2, is an OutgoingDraft or None: already covered.)
STATE_TYPES = [
    ("backoffice.graph.state", "ParsedEmail"),
    ("backoffice.graph.state", "Attachment"),
    ("backoffice.graph.state", "Classification"),
    ("backoffice.graph.state", "OutgoingDraft"),
    ("backoffice.graph.state", "DraftKind"),
    ("backoffice.graph.state", "HumanDecision"),
    ("backoffice.graph.state", "Decision"),
    ("backoffice.graph.state", "BookingExtraction"),             # step 10.2
    ("backoffice.services.booking_request", "BookingRequest"),   # step 10.2
    ("backoffice.services.availability", "AvailabilityResult"),  # step 10.3
    ("backoffice.services.availability", "AvailabilityStatus"),  # step 10.3
    ("backoffice.services.availability", "AlternativeStay"),     # step 10.3
    ("backoffice.services.pricing", "StayPrice"),                # step 10.3
]


def state_serializer() -> JsonPlusSerializer:
    """The serializer that saves/loads our state, allowed to recreate only STATE_TYPES."""
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


def memory_checkpointer() -> InMemorySaver:
    """
    An in-memory checkpointer (LangGraph's InMemorySaver: a Python dict inside this program).
    Shape of what it keeps, roughly: {thread_id: [checkpoint after read_email, after classify, ...]}
    """
    return InMemorySaver(serde=state_serializer())


# @contextmanager (plain Python) turns this function into something you use with `with`:
#     with postgres_checkpointer() as checkpointer:
#         graph = build_graph(checkpointer)
#         ...                                   # use it here
#     # here the connection is closed
# The code before `yield` runs when the `with` block starts, the yielded value is what you get
# after `as`, and the code after `yield` (here: closing the connection) runs when the block ends.
# Iterator[PostgresSaver] is only the type such a function has, for the editor.
@contextmanager
def postgres_checkpointer() -> Iterator[PostgresSaver]:
    """
    A checkpointer that saves every run's state in Postgres, over ONE open connection, closed when
    the `with` block ends.

    The connection settings are the ones LangGraph's PostgresSaver requires (they are what its own
    PostgresSaver.from_conn_string uses); we open the connection ourselves only to add our
    serializer and the 5-second timeout:
      autocommit=True      every statement is saved immediately (no transaction to commit): each
                           checkpoint is on disk as soon as the node finishes
      row_factory=dict_row rows come back as dicts {"column": value}; LangGraph's code reads them
                           that way
      prepare_threshold=0  turns off psycopg's "prepared statements" optimisation, which LangGraph
                           recommends turning off for its checkpoint queries
      connect_timeout=5    give up after 5 s if the database isn't running (same as db/connection.py)
    """
    with psycopg.connect(get_settings().database_url, autocommit=True, row_factory=dict_row,
                         prepare_threshold=0, connect_timeout=5) as conn:
        yield PostgresSaver(conn, serde=state_serializer())


def setup_checkpoint_tables() -> None:
    """
    Create LangGraph's checkpoint tables in Postgres (checkpoints, checkpoint_blobs,
    checkpoint_writes, checkpoint_migrations). PostgresSaver.setup() is LangGraph's method for it:
    safe to run again (it records which of its table versions it already created).
    Called by `uv run python -m backoffice.db.schema`, together with our own tables.
    """
    with postgres_checkpointer() as checkpointer:
        checkpointer.setup()
