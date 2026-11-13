/**
 * The whole page: three columns, like an email program.
 *
 *   LEFT: Inbox            MIDDLE: what the agent is doing        RIGHT: the result
 *   (10 demo emails)       (live log of the graph), the email     (why + the draft + Approve / Edit / Reject)
 *
 * WHAT HAPPENS WHEN ...
 *  1. the page opens:          load THIS VISITOR's inbox (GET /emails, with the visitor id) and draw it.
 *  2. the person clicks one:   load it (GET /emails/{name}) and show it in the middle. If it was processed
 *                              before (e.g. before a reload), also load its saved run (GET /runs/{id}):
 *                              the draft and the buttons come back, read from the Postgres checkpoint.
 *  3. they click "Process":    POST /emails/{name}/process and read the stream: each finished node adds
 *                              a line to the log (StepLog) at once; when the graph pauses at approval,
 *                              the draft appears on the right and the inbox is reloaded (badge "Waiting").
 *  4. they decide:             POST /runs/{id}/decision; the run resumes (approval -> action); its two
 *                              last steps are added to the log, the right column shows what was sent,
 *                              and the inbox is reloaded (badge "Approved" / "Edited" / "Rejected").
 *  5. they open the Sent tab:   GET /sent (this visitor's decisions); the sent messages are listed;
 *                              clicking one opens the original email and what was sent.
 *  6. they click "Process whole inbox": every email still "New" is processed ONE AFTER ANOTHER (3. for
 *                              each, the page follows along), then a summary: "10 emails: 7 handled,
 *                              2 need a person, 1 suspicious one blocked". Nothing is sent: every
 *                              draft still waits for its own decision.
 *
 * React terms:
 *  - useState: a value App remembers; calling its setter (e.g. setSelected("03_...")) redraws the page.
 *  - useEffect(fn, [x]): "run fn after drawing, and again whenever x changes". Used here to load
 *    data: once at the start ([] = never again), and each time the selected email changes.
 *  - setRuns(previous => ...): the "updater" form of a setter. Stream messages arrive one after another;
 *    each update starts from the LATEST value (previous), so no line is lost.
 *  - key={...} on a component: when the key changes, React starts that component afresh (e.g. the
 *    result panel forgets an unfinished edit when another email is selected).
 */

// React:
import { useEffect, useState } from "react";

// OURS:
import {
  fetchEmail,
  fetchInbox,
  fetchRun,
  fetchSent,
  LimitError,
  processEmail,
  sendDecision,
  type ApprovalRequest,
  type DecisionRequest,
  type EmailDetail,
  type EmailSummary,
  type OutgoingMessage,
  type SentItem,
  type StreamEvent,
} from "./api";
import { EmailView } from "./components/EmailView";
import { Inbox } from "./components/Inbox";
import { ResultPanel } from "./components/ResultPanel";
import { SchemaPanel } from "./components/SchemaPanel";
import { SentFolder } from "./components/SentFolder";
import { StepLog, type LoggedStep, type RunState } from "./components/StepLog";
import "./App.css";

/**
 * One run as the page knows it, kept per email while the page is open. Example (#3, paused at approval):
 *   { state: "waiting", threadId: "31917ec5-...", steps: [{ step: "read_email", label: "...", detail: {...}, seconds: 0.0 }, ...],
 *     approval: { outgoing_draft: { outgoing_to: "Sarah Mitchell <...>", ... }, ... }, decision: null, sent: null,
 *     reopened: false }
 * The log is NOT saved on the server: a run reopened after a reload (reopened: true) has its draft and
 * decision back, but no lines until the email is processed again.
 */
type Run = {
  state: RunState;
  threadId: string | null;
  steps: LoggedStep[];
  approval: ApprovalRequest | null;
  decision: string | null;
  sent: OutgoingMessage | null;
  reopened: boolean;
  error?: string;
};

/**
 * The summary after "Process whole inbox". Example (all 10 demo emails):
 *   { total: 10, handled: 7, needPerson: 2, suspicious: 1, failed: 0, seconds: 131 }
 *   handled    = a draft for the sender or for Accounts (reply_to_sender, ok_to_pay)
 *   needPerson = a note to the front desk (forward_to_staff), not suspicious
 *   suspicious = flagged by classify: blocked, forwarded to a person
 */
type BatchSummary = {
  total: number;
  handled: number;
  needPerson: number;
  suspicious: number;
  failed: number;
  seconds: number;
};

const BACKEND_DOWN = "Can't reach the backend. Please try again in a moment.";

export default function App() {
  const [emails, setEmails] = useState<EmailSummary[]>([]);           // the inbox rows
  const [selected, setSelected] = useState<string | null>(null);      // e.g. "03_booking_complete"
  const [email, setEmail] = useState<EmailDetail | null>(null);       // the selected email, once loaded
  const [error, setError] = useState<string | null>(null);            // e.g. "the backend isn't running"
  // The runs this page knows. Shape: { "03_booking_complete": Run, "06_question_pool_and_spa": Run, ... }
  const [runs, setRuns] = useState<Record<string, Run>>({});
  const [tab, setTab] = useState<"inbox" | "sent">("inbox");          // which list the left column shows
  const [sentItems, setSentItems] = useState<SentItem[]>([]);         // the Sent folder, once loaded
  const [batchRunning, setBatchRunning] = useState(false);            // "Process whole inbox" in progress
  const [runningEmail, setRunningEmail] = useState<string | null>(null);   // the email being processed now
  const [batchSummary, setBatchSummary] = useState<BatchSummary | null>(null);
  const [showSchema, setShowSchema] = useState(false);                // the bird's-eye view of the graph
  const [showPostcard, setShowPostcard] = useState(false);            // the postcard, full size

  function reloadInbox() {
    fetchInbox()
      .then((rows) => {
        setEmails(rows);
        // The backend answered: clear the "can't reach" message, but keep any other (e.g. a spending limit).
        setError((previous) => (previous === BACKEND_DOWN ? null : previous));
      })
      .catch(() => setError(BACKEND_DOWN));
  }

  function reloadSent() {
    fetchSent()
      .then(setSentItems)
      .catch((err: Error) => setError(err.message));
  }

  function openTab(which: "inbox" | "sent") {
    setTab(which);
    if (which === "sent") reloadSent();
  }

  // Change one email's run, starting from the latest value (see "updater form" above).
  function updateRun(name: string, change: Partial<Run>) {
    setRuns((previous) => ({ ...previous, [name]: { ...previous[name], ...change } }));
  }

  // 1. The page opens: load the inbox once.
  useEffect(reloadInbox, []);

  // 2. The person clicks an email: load it.
  useEffect(() => {
    if (selected === null) return;
    // `ignore`: if the person clicks another email before this one arrives, this answer is
    // thrown away, so a slow answer can never replace a newer one on screen.
    let ignore = false;
    setEmail(null);
    fetchEmail(selected)
      .then((loaded) => {
        if (!ignore) setEmail(loaded);
      })
      .catch((err: Error) => setError(err.message));
    // The function returned by an effect runs before the effect runs again (React's cleanup).
    return () => {
      ignore = true;
    };
  }, [selected]);

  // 2b. ... and if it was processed before but this page has no run for it (e.g. after a reload),
  // reopen the saved run from the server.
  const savedThreadId = emails.find((row) => row.name === selected)?.thread_id ?? null;
  const knownRun = selected !== null && runs[selected] !== undefined;
  useEffect(() => {
    if (selected === null || savedThreadId === null || knownRun) return;
    const name = selected;
    fetchRun(savedThreadId)
      .then((view) => {
        const reopened: Run = {
          state: view.status === "waiting" ? "waiting" : "finished",
          threadId: view.thread_id,
          steps: [],
          approval: view.approval_request,
          decision: view.decision,
          sent: view.sent,
          reopened: true,
        };
        // Only if no run was started meanwhile (e.g. the person clicked Process first).
        setRuns((previous) => (previous[name] ? previous : { ...previous, [name]: reopened }));
      })
      .catch(() => {
        // The run is gone (older than 2 hours): the inbox will show the email as new after a reload.
      });
  }, [selected, savedThreadId, knownRun]);

  // 3. The person clicks "Process": run the graph and log each step as it arrives.
  // Returns how the run ended, for "Process whole inbox": e.g. { state: "waiting", approval: {...} }.
  // limited = true when the server refused the run because a spending limit is reached (see LimitError).
  async function startRun(name: string): Promise<{ state: RunState; approval: ApprovalRequest | null; limited: boolean }> {
    let outcome = { state: "error" as RunState, approval: null as ApprovalRequest | null, limited: false };
    setRunningEmail(name);
    const fresh: Run = { state: "running", threadId: null, steps: [], approval: null, decision: null,
                         sent: null, reopened: false };
    setRuns((previous) => ({ ...previous, [name]: fresh }));

    let lastTime = performance.now();       // performance.now() (browser): a precise clock in milliseconds
    const onEvent = (event: StreamEvent) => {
      if (event.kind === "start") {
        updateRun(name, { threadId: event.data.thread_id });
      } else if (event.kind === "step") {
        const now = performance.now();
        const logged: LoggedStep = { ...event.data, seconds: (now - lastTime) / 1000 };
        lastTime = now;
        setRuns((previous) => ({
          ...previous,
          [name]: { ...previous[name], steps: [...previous[name].steps, logged] },
        }));
      } else if (event.kind === "done") {
        const approval = event.data.waiting_for_human;
        outcome = { state: approval ? "waiting" : "finished", approval, limited: false };
        updateRun(name, { state: outcome.state, approval });
      } else if (event.kind === "error") {
        updateRun(name, { state: "error", error: event.data.error });
      }
    };

    try {
      await processEmail(name, onEvent);
    } catch (err) {
      updateRun(name, { state: "error", error: (err as Error).message });
      if (err instanceof LimitError) {
        outcome = { state: "error", approval: null, limited: true };
        setError(err.message);               // shown in the red banner under the header
      }
    }
    setRunningEmail(null);
    reloadInbox();                           // the badge changes to "Waiting for approval"
    return outcome;
  }

  // 6. "Process whole inbox": every email still "New", one after another, then the summary.
  // One after another (not all at once): the visitor can follow each run, and the APIs (Claude,
  // Voyage) are not hit with 10 runs at the same moment.
  async function processWholeInbox() {
    const todo = emails.filter((row) => row.status === "new" && !runs[row.name]).map((row) => row.name);
    if (todo.length === 0) return;
    setBatchRunning(true);
    setBatchSummary(null);
    setTab("inbox");
    const started = performance.now();
    const summary: BatchSummary = { total: todo.length, handled: 0, needPerson: 0, suspicious: 0, failed: 0, seconds: 0 };
    for (const name of todo) {
      setSelected(name);                     // the page follows along: email in the middle, log as it runs
      const { approval, limited } = await startRun(name);
      if (limited) {
        summary.total -= todo.length - todo.indexOf(name);   // the emails not processed are not counted
        break;                                                // a spending limit: stop the batch here
      }
      if (approval === null) summary.failed += 1;
      else if (approval.suspicious) summary.suspicious += 1;
      else if (approval.outgoing_draft.kind === "forward_to_staff") summary.needPerson += 1;
      else summary.handled += 1;
    }
    summary.seconds = Math.round((performance.now() - started) / 1000);
    setBatchSummary(summary);
    setBatchRunning(false);
  }

  // 4. The person decides: resume the run, add its last steps to the log, show what was sent.
  async function decide(name: string, threadId: string, request: DecisionRequest) {
    const started = performance.now();
    const view = await sendDecision(threadId, request);       // an error here is shown by ResultPanel
    const seconds = (performance.now() - started) / 1000;
    // The resumed steps (approval, action) arrive together: the time is the whole decision's.
    // `?? []`: no steps if the run was decided elsewhere (see sendDecision) or by an older backend.
    const lastSteps: LoggedStep[] = (view.steps ?? []).map((step, index) => ({ ...step, seconds: index === 0 ? seconds : 0 }));
    setRuns((previous) => ({
      ...previous,
      [name]: {
        ...previous[name],
        state: "finished",
        steps: [...previous[name].steps, ...lastSteps],
        approval: null,
        decision: view.decision,
        sent: view.sent,
      },
    }));
    reloadInbox();                           // the badge changes to Approved / Edited / Rejected
    reloadSent();                            // and the Sent folder gains the message
  }

  const run = selected !== null ? runs[selected] : undefined;
  const summary = emails.find((row) => row.name === selected);
  // Show "Process" only for an email with no run yet (or after a run that crashed).
  const canProcess = summary !== undefined && (run ? run.state === "error" : summary.status === "new");

  return (
    <div className="app">
      <header className="app-header">
        <button className="postcard" onClick={() => setShowPostcard(true)} aria-label="Show the postcard full size">
          <img src="/overlook-postcard.jpg" alt="Postcard of The Overlook Hotel, Sidewinder, Colorado" />
        </button>
        <div className="brand">
          <span className="brand-name">The Overlook<br />Hotel</span>
          <span className="brand-sub">Back office · Sidewinder, Colorado</span>
        </div>
        <p className="app-note">
          Email &amp; document automation. Pick an email, let the agent process it, then approve, edit or reject
          what it drafted. Nothing is really sent; your inbox is private to this browser and cleared after 2 hours.
        </p>
        <button className="schema-button" onClick={() => setShowSchema(true)}>
          Show me how it works
          <span className="schema-button-sub">under the hood</span>
          <span className="schema-button-room">Room 237</span>
        </button>
      </header>
      {/* The hexagon carpet strip (drawn in App.css). aria-hidden: decoration, screen readers skip it. */}
      <div className="hex-strip" aria-hidden="true" />

      {showSchema && (
        <SchemaPanel
          steps={run ? run.steps.map((step) => step.step) : []}
          waiting={run?.state === "waiting"}
          emailSubject={email?.subject ?? null}
          onClose={() => setShowSchema(false)}
        />
      )}
      {showPostcard && (
        <div className="overlay overlay-postcard" onClick={() => setShowPostcard(false)}>
          <img src="/overlook-postcard.jpg" alt="Postcard of The Overlook Hotel, Sidewinder, Colorado" />
        </div>
      )}

      {batchSummary && (
        <div className="summary-banner" role="status">
          <strong>
            {batchSummary.total} emails processed in {batchSummary.seconds} s: {batchSummary.handled} handled,{" "}
            {batchSummary.needPerson} need a person, {batchSummary.suspicious} suspicious{" "}
            {batchSummary.suspicious === 1 ? "one" : "ones"} blocked
            {batchSummary.failed > 0 && `, ${batchSummary.failed} failed`}.
          </strong>{" "}
          Nothing has been sent: every draft waits for your approval. Click an email to review it.
          <button className="link-button" onClick={() => setBatchSummary(null)}>
            Close
          </button>
        </div>
      )}

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      <main className="columns">
        <nav className="inbox" aria-label="Mail folders">
          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === "inbox"} className={tab === "inbox" ? "tab active" : "tab"}
                    onClick={() => openTab("inbox")}>
              Inbox <span className="count">{emails.length}</span>
            </button>
            <button role="tab" aria-selected={tab === "sent"} className={tab === "sent" ? "tab active" : "tab"}
                    onClick={() => openTab("sent")}>
              Sent
            </button>
          </div>
          {tab === "inbox" && (
            <>
              <button
                className="primary-button whole-inbox"
                disabled={batchRunning || runningEmail !== null || !emails.some((row) => row.status === "new")}
                onClick={processWholeInbox}
              >
                {batchRunning ? "Processing the inbox…" : "Process whole inbox"}
              </button>
              <Inbox emails={emails} selected={selected} running={runningEmail} onSelect={setSelected} />
            </>
          )}
          {tab === "sent" && <SentFolder items={sentItems} selected={selected} onSelect={setSelected} />}
        </nav>

        <section className="column middle" aria-label="What the agent is doing">
          {selected === null && <p className="empty">Select an email from the inbox.</p>}

          {selected !== null && (
            <>
              {(canProcess || run?.state === "running") && (
                <div className="process-bar">
                  <button
                    className="primary-button"
                    disabled={run?.state === "running" || batchRunning}
                    onClick={() => startRun(selected)}
                  >
                    {run?.state === "running" ? "Processing…" : run ? "Try again" : "Process with the agent"}
                  </button>
                </div>
              )}

              {run && run.steps.length > 0 && (
                <section className="agent-steps">
                  <h2 className="column-title">
                    What the agent did · click a step to see its data
                    {run.threadId && <span className="thread-id"> · run {run.threadId.slice(0, 8)}</span>}
                  </h2>
                  <StepLog steps={run.steps} state={run.state} error={run.error} />
                </section>
              )}
              {/* No line yet: still starting, or it failed before the first step (show why). */}
              {run && (run.state === "running" || run.state === "error") && run.steps.length === 0 && (
                <section className="agent-steps">
                  <StepLog steps={[]} state={run.state} error={run.error} />
                </section>
              )}
              {run?.reopened && (
                <p className="empty">
                  Processed earlier: the draft and decision were reloaded from the saved run (the LangGraph
                  checkpoint in Postgres). The step log is only kept while the page is open.
                </p>
              )}

              {email === null && <p className="empty">Loading…</p>}
              {email !== null && <EmailView email={email} />}
            </>
          )}
        </section>

        <section className="column result" aria-label="Result">
          <h2 className="column-title">Result</h2>
          <ResultPanel
            key={run?.threadId ?? selected ?? "none"}
            approval={run?.approval ?? null}
            decision={run?.decision ?? null}
            sent={run?.sent ?? null}
            onDecide={(request) => {
              if (selected === null || !run?.threadId) return Promise.resolve();
              return decide(selected, run.threadId, request);
            }}
          />
        </section>
      </main>
    </div>
  );
}
