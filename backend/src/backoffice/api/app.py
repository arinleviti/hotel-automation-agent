"""The backend API (step 15): what the server does when the person on the web page does something.

The API sits OUTSIDE the graph: the graph never knows about HTTP. Each endpoint calls the same
functions as the command line (main_graph.py), so there are two front doors to one system:

    browser ──HTTP──► endpoint (this file) ──► iter_steps / run_result / resume_email ──► LangGraph

=================================================================================================
WHAT HAPPENS WHEN ..., one endpoint per moment on the page
=================================================================================================

1. ... THE PAGE OPENS (and again after every decision, to refresh the list)
       GET /emails
   The server reads the From / Subject / Date of every .eml file in data/emails/ (headers only, no
   PDF parsing: fast) and looks up, in the database, whether each email has been processed and
   decided. The files stay on the server; it sends back only a list:
       [{"name": "03_booking_complete", "sender": "Sarah Mitchell <...>", "subject": "Room availability ...",
         "date": "2026-11-02T18:41:00-07:00", "status": "new", "thread_id": null}, ... 10 ...]
   The page draws the LEFT column (the inbox) from it, with a badge per email: new / waiting /
   approve / edit / reject.

2. ... THE PERSON CLICKS AN EMAIL (or "Process whole inbox", which does this for each email in turn)
       POST /emails/03_booking_complete/process
   The server checks the name is one of the demo emails, starts a new run of the graph for it,
   and SENDS EACH STEP AS SOON AS IT FINISHES (a stream, see "SSE" below):
       "Read the email from Sarah Mitchell" → "Claude classified it: booking (0.97)" → ...
       → "Price calculated in code: $1,440.72" → "Draft written ..."
   then, when the graph pauses at approval, the draft and its evidence. The page shows the steps
   appearing one by one in the MIDDLE column, then the draft with Approve / Edit / Reject in the
   RIGHT column.

1b. ... THE PERSON CLICKS AN EMAIL TO READ IT (step 16.1)
       GET /emails/01_invoice_front_range_provisions
   The server opens the .eml file and sends back sender, to, subject, date, the body text and the
   NAMES of the attachments (no graph, no Docling):
       {"name": "01_invoice_...", "sender": "Denise Walker <billing@frontrangeprovisions.example>", ...,
        "body": "Hi, Please find attached ...", "attachments": [{"filename": "FRP-INV-2026-1184.pdf", ...}]}
   The page shows the email; for each PDF it asks for the file itself:
       GET /emails/01_invoice_front_range_provisions/attachments/FRP-INV-2026-1184.pdf
   and the server sends the PDF's bytes, which the browser's own PDF viewer displays.

3. ... THE PERSON OPENS AN EMAIL THAT WAS ALREADY PROCESSED (e.g. after reloading the page)
       GET /runs/{thread_id}
   No new run: the server reads the saved run (the checkpoint) and sends back either the draft +
   evidence (still waiting for a decision) or the decision and what was sent. The page shows it in
   the RIGHT column without running the graph again.

4. ... THE PERSON CLICKS APPROVE, EDIT (after changing the text) OR REJECT
       POST /runs/{thread_id}/decision      body: {"decision": "approve"}
   The server checks the answer's shape (an edit must include the new text), then resumes the
   paused run: approval -> action (one row in `actions`) -> END. It sends back the outcome
   ("approve, sent to Sarah Mitchell") and the steps the run took (approval, action). The page adds
   those to the log, shows the confirmation and refreshes the inbox (1.).

5. ... THE PERSON OPENS THE "SENT" FOLDER
       GET /sent
   The server reads the `actions` table and sends back every decision, newest first: what was
   sent, to whom, or what was rejected. The page lists them.

(Also GET /health: "is the server up?". Not used by the page; the hosting platform calls it, step 18.)

=================================================================================================
ONE PRIVATE INBOX PER VISITOR (step 16.2)
=================================================================================================
The demo is public: if every visitor shared one inbox, a recruiter would find emails already
approved by the previous visitor. So:
  - the browser makes a random id the first time the page opens (e.g. "7c1e2b0a-4f5d-...") and
    keeps it; every request carries it in the header  X-Visitor-Id: 7c1e2b0a-...
  - each run is saved with that id (runs.visitor_id); the inbox status (1.) and the Sent folder (5.)
    show only this visitor's runs and decisions; a visitor can open or decide only their own runs (3., 4.)
  - every run older than 2 hours is deleted (with its decision and its saved graph state), each time
    the inbox loads or a run starts.
Not security (fake data, no login): a real deployment would use the staff member's login instead.

Run (from backend/; Postgres running):
    uv run uvicorn backoffice.api.app:app --reload --port 8000
    then http://localhost:8000/docs  (FastAPI's automatic, clickable docs)

=================================================================================================
STREAMING THE STEPS: Server-Sent Events (SSE)
=================================================================================================
SSE = a standard way for a server to send a SERIES of messages over one HTTP response; the browser
reads them as they arrive (EventSource / fetch). Each message is text in this format:
    event: step
    data: {"step": "classify", "label": "Claude classified it: booking (confidence 0.95)", "detail": {...}}
    <empty line = end of this message>
"detail" = what that node added to the state (steps.step_detail): the page shows it when the person
clicks the line. For POST /emails/03_booking_complete/process the stream is:
    event: start  data: {"thread_id": "31917ec5-...", "email": "03_booking_complete"}
    event: step   data: {"step": "read_email", "label": "Read the email from Sarah Mitchell <...>"}
    event: step   data: {"step": "classify", "label": "Claude classified it: booking (confidence 0.95)",
                         "detail": {"classification": {"type": "booking", "suspicious": false, "confidence": 0.95, ...}}}
    ...
    event: step   data: {"step": "booking_branch > price_stay", "label": "Price calculated in code: $1,440.72"}
    event: done   data: {"thread_id": "31917ec5-...", "waiting_for_human": {...the approval request...}}
(or `event: error` if the run itself crashed; since step 13 a failed node already becomes a note
to the front desk, so that should only happen if approval or the database is down).

How: event_stream() in process() is a generator; for each step iter_steps hands back, it yields
one SSE message, and FastAPI's StreamingResponse sends it at once. No threads or queues of ours.
The graph stays synchronous (decided 2026-11-13, option B).
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import json                                    # json.dumps: Python dict -> JSON text
from pathlib import Path                       # where the built page (frontend/dist) is
import uuid                                    # uuid.uuid4(): a new thread_id per run
from datetime import timedelta                 # "2 hours": how long a demo run is kept
from contextlib import ExitStack, asynccontextmanager   # keep the Postgres connection open while the app runs
from dataclasses import asdict                 # dataclass -> dict (for JSON)
from email import policy                       # policy.default: read emails with the modern API (EmailMessage)
from email.message import EmailMessage         # one parsed email: message["From"], its parts and attachments
from email.parser import BytesParser           # read an .eml file (all of it, or its headers only)

# FastAPI (the web framework) and Starlette (the library FastAPI is built on):
from fastapi import FastAPI, Header, HTTPException
# FastAPI: the app; Header: read a request header into a parameter; HTTPException: answer with an error code
from fastapi.middleware.cors import CORSMiddleware   # CORS: which websites may call this API from a browser
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles    # serves the built page's files (step 18)
# Response: a reply with raw bytes (an attached PDF); StreamingResponse: sent piece by piece (our SSE stream)

# LangGraph:
from langgraph.types import Command            # Command(resume=answer): resume a run paused at interrupt()

# OURS:
from backoffice.api.schemas import AttachmentInfo, EmailDetail, EmailSummary, RunView, SentItem
from backoffice.api.steps import describe_step, step_detail
from backoffice.config import get_settings
from backoffice.db.connection import connect
from backoffice.db.queries import (count_recent_runs, delete_old_runs, load_actions, load_latest_runs, load_run_visitor,
                                   save_run)
from backoffice.graph.checkpointer import postgres_checkpointer
from backoffice.graph.main_graph import EMAILS_DIR, build_graph, email_path_for, iter_steps, run_config, run_result
from backoffice.graph.state import HumanDecision


# --- Database access (small functions so the tests can swap them for fakes) -------------------------

def db_save_run(thread_id: str, email_name: str, visitor_id: str) -> None:
    with connect() as conn:
        save_run(conn, thread_id, email_name, visitor_id)


def db_latest_runs(visitor_id: str) -> dict[str, dict]:
    with connect() as conn:
        return load_latest_runs(conn, visitor_id)


def db_actions(visitor_id: str) -> list[dict]:
    with connect() as conn:
        return load_actions(conn, visitor_id)


def db_run_visitor(thread_id: str) -> str | None:
    with connect() as conn:
        return load_run_visitor(conn, thread_id)


def db_count_recent_runs(visitor_id: str) -> tuple[int, int]:
    with connect() as conn:
        return count_recent_runs(conn, visitor_id)


def db_delete_old_runs() -> list[str]:
    with connect() as conn:
        return delete_old_runs(conn, KEEP_RUNS_FOR)


# The built page (step 18): frontend/dist, next to backend/ (repo root = 4 folders up from this file).
PAGE_DIR = Path(__file__).resolve().parents[4] / "frontend" / "dist"

# How long a visitor's demo runs are kept (decided 2026-11-13).
KEEP_RUNS_FOR = timedelta(hours=2)

# What a visitor id may look like: letters, digits and dashes, 8 to 64 characters (a uuid is 36).
# Anything else is refused (422) before any database access.
VISITOR_ID_PATTERN = r"^[A-Za-z0-9-]{8,64}$"


# --- The app --------------------------------------------------------------------------------------

def create_app(graph=None) -> FastAPI:
    """
    Build the FastAPI app.

    graph: None (the real server) = build the graph with the POSTGRES checkpointer, so a paused run
    survives a restart and the decision can come in any later request. Tests pass a graph with the
    in-memory checkpointer instead.

    lifespan (FastAPI): code that runs when the server starts (before `yield`) and when it stops
    (after). Here: open the Postgres connection for the checkpointer at start, close it at stop.
    ExitStack (plain Python) = "remember the `with` blocks I entered, close them all later".
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ExitStack() as stack:
            if graph is None:
                checkpointer = stack.enter_context(postgres_checkpointer())
                app.state.graph = build_graph(checkpointer)
            else:
                app.state.graph = graph
            yield                              # the server runs here

    app = FastAPI(title="Overlook back-office API",
                  description="Email and document automation for The Overlook Hotel (portfolio demo).",
                  lifespan=lifespan)
    # CORS: allow the frontend's address(es) to call this API from the browser.
    app.add_middleware(CORSMiddleware,
                       allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
                       allow_methods=["*"], allow_headers=["*"])

    # @app.get("/path") (FastAPI) = "when a GET request for /path arrives, call this function".
    # A plain `def` (not async) runs in FastAPI's worker threads, so a slow graph run doesn't block
    # other requests. The return value (a Pydantic model or list) is turned into JSON automatically.

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    def forget_old_runs() -> None:
        """Delete runs older than 2 hours: their rows (db_delete_old_runs) and their saved graph states."""
        for thread_id in db_delete_old_runs():
            # delete_thread (LangGraph checkpointer): remove every checkpoint saved for this run
            app.state.graph.checkpointer.delete_thread(thread_id)

    # Header(pattern=...) (FastAPI): read the request header "X-Visitor-Id" into `x_visitor_id`
    # (FastAPI turns the underscores into dashes); missing or wrongly shaped -> 422.

    @app.get("/emails", response_model=list[EmailSummary])
    def list_emails(x_visitor_id: str = Header(pattern=VISITOR_ID_PATTERN)) -> list[EmailSummary]:
        """The inbox: every demo email, oldest first, with THIS VISITOR's latest run's status."""
        forget_old_runs()
        runs = db_latest_runs(x_visitor_id)
        inbox = []
        for path in sorted(EMAILS_DIR.glob("*.eml")):
            with path.open("rb") as file:
                # headersonly=True: read From/Subject/Date only, not the body or attachments.
                headers = BytesParser(policy=policy.default).parse(file, headersonly=True)
            run = runs.get(path.stem)
            if run is None:
                status, thread_id = "new", None
            else:
                status, thread_id = (run["decision"] or "waiting"), run["thread_id"]
            date = headers["Date"].datetime if headers["Date"] is not None else None
            inbox.append(EmailSummary(name=path.stem, sender=str(headers["From"]), subject=str(headers["Subject"]),
                                      date=date, status=status, thread_id=thread_id))
        return inbox

    @app.get("/emails/{name}", response_model=EmailDetail)
    def get_email(name: str) -> EmailDetail:
        """
        WHEN the person clicks an email in the inbox: the server opens that .eml file and sends back
        what a mail program shows (sender, subject, date, body) and the NAMES of its attachments.
        No graph, no Docling: just reading the file.
        """
        message = open_demo_email(name)
        attachments = [AttachmentInfo(filename=part.get_filename() or "attachment",
                                      content_type=part.get_content_type(),
                                      size=len(part.get_payload(decode=True) or b""))
                       for part in message.iter_attachments()]
        # get_body(preferencelist=("plain",)) (email module): the plain-text part of the email.
        body_part = message.get_body(preferencelist=("plain",))
        body = body_part.get_content() if body_part is not None else ""
        date = message["Date"].datetime if message["Date"] is not None else None
        return EmailDetail(name=name, sender=str(message["From"]), to=str(message["To"]),
                           subject=str(message["Subject"]), date=date, body=body, attachments=attachments)

    @app.get("/emails/{name}/attachments/{filename}")
    def get_attachment(name: str, filename: str) -> Response:
        """
        WHEN the email view shows an attached PDF: the browser asks for the file itself, and the
        server sends its bytes. The browser's own PDF viewer displays it (no PDF library on the page).
        Only a file that really is attached to that demo email can come back: the name is looked up
        among the email's attachments, never used as a path on disk.
        """
        message = open_demo_email(name)
        for part in message.iter_attachments():
            if part.get_filename() == filename:
                # get_payload(decode=True) (email module): the file's bytes, decoded from the email's text form.
                # Content-Disposition "inline" = "show it in the page", not "download it".
                return Response(content=part.get_payload(decode=True), media_type=part.get_content_type(),
                                headers={"Content-Disposition": f'inline; filename="{filename}"'})
        raise HTTPException(status_code=404, detail=f"No attachment called {filename!r} in {name!r}")

    @app.post("/emails/{name}/process")
    def process(name: str, x_visitor_id: str = Header(pattern=VISITOR_ID_PATTERN)) -> StreamingResponse:
        """Start a run for one demo email and stream its steps (SSE, see the top of this file)."""
        try:
            email_path = str(email_path_for(name))        # only demo emails: no other file can be opened
        except ValueError:
            raise HTTPException(status_code=404, detail=f"No demo email called {name!r}")
        thread_id = str(uuid.uuid4())
        forget_old_runs()
        check_spending_limits(x_visitor_id)
        db_save_run(thread_id, name, x_visitor_id)

        def event_stream():
            """
            The stream itself. A generator (plain Python `yield`): FastAPI sends each yielded
            text to the browser AS SOON AS it is yielded, then asks for the next one.
            The graph runs INSIDE this loop: iter_steps (main_graph.py) runs graph.stream(...)
            and hands back each node's result the moment that node finishes.
            Langfuse is not needed here: run_config (main_graph.py) already gives the graph
            its Langfuse callback, so every node is traced whoever starts the run.
            """
            yield sse("start", {"thread_id": thread_id, "email": name})
            try:
                steps = []
                for step, added in iter_steps(app.state.graph, {"email_path": email_path}, thread_id):
                    steps.append(step)
                    yield sse("step", {"step": step, "label": describe_step(step, added),
                                       "detail": step_detail(added)})
                result = run_result(app.state.graph, thread_id, steps)
                yield sse("done", {"thread_id": thread_id, "waiting_for_human": result.waiting_for_human})
            except Exception as error:
                # Since step 13 a failed node already becomes a note to the front desk; this only
                # happens if approval or the database itself is down.
                yield sse("error", {"thread_id": thread_id, "error": f"{type(error).__name__}: {error}"})

        # StreamingResponse (FastAPI): a response sent piece by piece, one piece per `yield` above.
        # media_type "text/event-stream" tells the browser "this is SSE".
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/runs/{thread_id}", response_model=RunView)
    def get_run(thread_id: str, x_visitor_id: str = Header(pattern=VISITOR_ID_PATTERN)) -> RunView:
        """A run, read from its checkpoint: waiting (the approval request) or finished (what was sent)."""
        check_owner(thread_id, x_visitor_id)
        snapshot = app.state.graph.get_state(run_config(thread_id))
        if not snapshot.values:
            raise HTTPException(status_code=404, detail="No run with this thread_id")
        return view_of(thread_id, snapshot)

    @app.post("/runs/{thread_id}/decision", response_model=RunView)
    def decide(thread_id: str, decision: HumanDecision,
               x_visitor_id: str = Header(pattern=VISITOR_ID_PATTERN)) -> RunView:
        """
        The staff member's answer. FastAPI checks the request body against HumanDecision first (a
        wrong shape -> 422, before the graph is touched); then the paused run resumes:
        approval -> action -> END. The answer: the finished run (decision + what was sent) and the
        steps of this second half, e.g.
            {"thread_id": "...", "status": "finished", "decision": "approve", "sent": {"outgoing_to": ...},
             "steps": [{"step": "approval", "label": "Staff decision: approve", "detail": {...}},
                       {"step": "action", "label": "Recorded: sent to Front Range Provisions <...>", "detail": {...}}]}
        """
        check_owner(thread_id, x_visitor_id)
        graph = app.state.graph
        # Refuse an answer for a run that isn't waiting (already decided): same rule as resume_email.
        # get_state(...).interrupts (LangGraph) = the questions the run is waiting on; () = none.
        if not graph.get_state(run_config(thread_id)).interrupts:
            raise HTTPException(status_code=409, detail="This run is not waiting for a decision")
        # Resume the paused run with the answer, and keep each step it runs (approval, then action),
        # so the page can add them to its log, like the steps of the first half.
        # Command(resume=...) (LangGraph): "this is the answer to the waiting interrupt()".
        steps = []
        for step, added in iter_steps(graph, Command(resume=decision.model_dump(mode="json")), thread_id):
            steps.append({"step": step, "label": describe_step(step, added), "detail": step_detail(added)})
        view = view_of(thread_id, graph.get_state(run_config(thread_id)))
        view.steps = steps
        return view

    @app.get("/sent", response_model=list[SentItem])
    def sent(x_visitor_id: str = Header(pattern=VISITOR_ID_PATTERN)) -> list[dict]:
        """The Sent folder: THIS VISITOR's decisions recorded by the action node, newest first."""
        return db_actions(x_visitor_id)

    # Step 18: in the deployed container, the built page (npm run build -> frontend/dist) is served by
    # this same app, so the page and the API share one address. StaticFiles (FastAPI/Starlette) answers
    # any path no endpoint above matched with a file from that folder; html=True: "/" -> index.html.
    # Mounted LAST, so it never hides an endpoint. Locally (no dist folder) nothing is mounted: the
    # page comes from Vite's dev server instead.
    if PAGE_DIR.is_dir():
        app.mount("/", StaticFiles(directory=PAGE_DIR, html=True), name="page")

    return app


def check_spending_limits(visitor_id: str) -> None:
    """
    Refuse a new run (HTTP 429 "Too Many Requests") when the demo's limits are reached (step 18):
    this visitor has started RUN_LIMIT_PER_VISITOR runs in the last 2 hours, or all visitors together
    RUN_LIMIT_PER_HOUR in the last hour. The message is shown to the visitor as it is.
    Example: the 31st run of one visitor -> 429 "You've processed 30 emails in the last 2 hours ..."
    """
    settings = get_settings()
    mine, everyone = db_count_recent_runs(visitor_id)
    if mine >= settings.run_limit_per_visitor:
        raise HTTPException(status_code=429, detail=(
            f"You've processed {mine} emails in the last 2 hours, the demo's limit per visitor "
            "(each run calls paid AI services). Please come back a little later."))
    if everyone >= settings.run_limit_per_hour:
        raise HTTPException(status_code=429, detail=(
            "The demo is very busy right now (its hourly limit of AI calls is reached). "
            "Please try again in a while."))


def check_owner(thread_id: str, visitor_id: str) -> None:
    """
    A visitor may open or decide only their OWN runs. Someone else's run, or no run at all, gets the
    same answer (404), so a visitor can't even tell whether another visitor's run exists.
    """
    if db_run_visitor(thread_id) != visitor_id:
        raise HTTPException(status_code=404, detail="No run with this thread_id")


def open_demo_email(name: str) -> EmailMessage:
    """
    Open one demo email by name (e.g. "06_question_pool_and_spa") and return it as an EmailMessage
    (email module: headers like message["From"], plus its parts). Unknown name -> 404.
    email_path_for (ours) only accepts names of files in data/emails/, so no other file can be opened.
    """
    try:
        path = email_path_for(name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"No demo email called {name!r}")
    with path.open("rb") as file:
        return BytesParser(policy=policy.default).parse(file)


def view_of(thread_id: str, snapshot) -> RunView:
    """
    A checkpoint snapshot as a RunView.
      waiting  (paused at approval): approval_request = snapshot.interrupts[0].value
      finished (after action):       decision + sent (the final outgoing message as a dict, or None)
    """
    if snapshot.interrupts:
        return RunView(thread_id=thread_id, status="waiting", approval_request=snapshot.interrupts[0].value)
    values = snapshot.values
    decision = values.get("final_human_decision")
    sent_message = values.get("final_outgoing_message")
    return RunView(thread_id=thread_id, status="finished",
                   decision=str(decision.decision) if decision else None,
                   sent=asdict(sent_message) if sent_message else None)


def sse(kind: str, payload: dict) -> str:
    """
    One message in the SSE text format, e.g.
        sse("step", {"step": "classify", "label": "Claude classified it: booking (confidence 0.95)"})
        -> 'event: step\ndata: {"step": "classify", "label": "..."}\n\n'
    json.dumps(default=str): anything json can't write itself (dates, Decimals) is written as text.
    The empty line at the end ("\n\n") marks the end of the message.
    """
    return f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"


# The app uvicorn runs: `uv run uvicorn backoffice.api.app:app`
app = create_app()
