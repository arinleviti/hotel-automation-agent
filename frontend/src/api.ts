/**
 * Everything the page asks the backend (backend/src/backoffice/api/app.py), in one file.
 *
 * WHAT HAPPENS: each function sends one HTTP request with `fetch` (built into every browser:
 * "go to this address and bring back the answer") and returns the JSON, already typed.
 *
 * The `type`s below are the SAME shapes as the backend's Pydantic models (api/schemas.py),
 * written again in TypeScript, so a typo like `email.sendr` is caught before the page runs.
 */

// OURS:
import { visitorId } from "./visitor";

// Where the backend runs. import.meta.env (Vite): settings fixed when the page is built.
//   VITE_API_URL set           -> that address (e.g. Claude's preview servers on port 8010)
//   development (npm run dev)  -> the local uvicorn server, http://localhost:8000
//   production (npm run build) -> "" = the SAME address the page came from: in the deployed container
//                                 FastAPI serves both the page and the API (step 18), so no CORS needed.
export const API_BASE: string =
  import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

// --- Shapes (mirror api/schemas.py) --------------------------------------------------------------

/**
 * One row of the inbox. Example:
 *   { name: "03_booking_complete", sender: "Sarah Mitchell <sarah.mitchell@mail.example>",
 *     subject: "Room availability December 18-21", date: "2026-11-02T18:41:00-07:00",
 *     status: "waiting", thread_id: "31917ec5-..." }
 */
export type EmailSummary = {
  name: string;
  sender: string;
  subject: string;
  date: string | null;           // JSON has no date type: it arrives as text (ISO format)
  status: EmailStatus;
  thread_id: string | null;
};

// "new" = never processed; "waiting" = paused at approval; or the decision taken.
export type EmailStatus = "new" | "waiting" | "approve" | "edit" | "reject";

/** One attached file (its name only). Example: { filename: "FRP-INV-2026-1184.pdf", content_type: "application/pdf", size: 41873 } */
export type AttachmentInfo = {
  filename: string;
  content_type: string;
  size: number;
};

/**
 * One email, as the person reads it. Example (#1):
 *   { name: "01_invoice_front_range_provisions", sender: "Front Range Provisions <billing@...>",
 *     to: "The Overlook Hotel <info@overlook-hotel.example>", subject: "Invoice FRP-INV-2026-1184 - ...",
 *     date: "2026-10-30T...", body: "Hi,\n\nPlease find attached ...",
 *     attachments: [{ filename: "FRP-INV-2026-1184.pdf", ... }] }
 */
export type EmailDetail = {
  name: string;
  sender: string;
  to: string;
  subject: string;
  date: string | null;
  body: string;
  attachments: AttachmentInfo[];
};

/**
 * One step of the graph, as the stream sends it (step 16.2). Example:
 *   { step: "booking_branch > price_stay",
 *     label: "Price calculated in code: $1,440.72",
 *     detail: { stay_price: { nights: 3, subtotal: "1305.00", tax: "135.72", total_price: "1440.72", ... } } }
 * step   = the node's real name; "branch > node" for a node inside a branch (a subgraph)
 * detail = what the node added to the state (any JSON: shown as a tree when the line is clicked)
 */
export type StepEvent = {
  step: string;
  label: string;
  detail: Record<string, unknown>;
};

/**
 * What the approval node hands to a person (the graph is paused here). Example (#3):
 *   { incoming: { sender: "Sarah Mitchell <...>", subject: "Room availability December 18-21" },
 *     route: "booking", reason_for_human_review: "",
 *     evidence: { read_as: "Friday, December 18 to Monday, December 21, 2026; 2 adults and 1 child", ... },
 *     outgoing_draft: { kind: "reply_to_sender", outgoing_to: "Sarah Mitchell <...>",
 *                       outgoing_subject: "Re: Room availability December 18-21", outgoing_body: "Dear Sarah, ...", reason: "..." } }
 */
export type ApprovalRequest = {
  incoming: { sender: string; subject: string };
  route: string;
  suspicious: boolean;              // classify flagged it (e.g. #9): counted apart in the whole-inbox summary
  reason_for_human_review: string;
  evidence: Record<string, unknown>;
  outgoing_draft: {
    kind: string;
    outgoing_to: string;
    outgoing_subject: string;
    outgoing_body: string;
    reason: string;
  };
};

/**
 * The messages of the process stream, in order: one "start", one "step" per node, then "done"
 * (or "error"). Each is { kind, data }; TypeScript knows which `data` goes with which `kind`.
 */
export type StreamEvent =
  | { kind: "start"; data: { thread_id: string; email: string } }
  | { kind: "step"; data: StepEvent }
  | { kind: "done"; data: { thread_id: string; waiting_for_human: ApprovalRequest | null } }
  | { kind: "error"; data: { thread_id: string; error: string } };

// --- Requests -------------------------------------------------------------------------------------

/** The header that says which visitor is asking (see visitor.ts). Example: { "X-Visitor-Id": "7c1e2b0a-..." } */
function visitorHeaders(): Record<string, string> {
  return { "X-Visitor-Id": visitorId() };
}

/** Send a GET request and return the JSON; any error code (404, 500 ...) becomes an Error. */
async function getJson<T>(path: string): Promise<T> {
  // `async` / `await` (JavaScript): fetch takes time; `await` waits for the answer without freezing the page.
  const response = await fetch(`${API_BASE}${path}`, { headers: visitorHeaders() });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} for ${path}`);
  }
  return (await response.json()) as T;
}

/** WHEN the page opens (and after every decision): GET /emails -> the 10 inbox rows. */
export function fetchInbox(): Promise<EmailSummary[]> {
  return getJson<EmailSummary[]>("/emails");
}

/** WHEN the person clicks an email: GET /emails/{name} -> sender, subject, body, attachment names. */
export function fetchEmail(name: string): Promise<EmailDetail> {
  // encodeURIComponent (JavaScript): makes the name safe to put in an address.
  return getJson<EmailDetail>(`/emails/${encodeURIComponent(name)}`);
}

/**
 * The address of an attached file. Not a request: the page puts this address in an <iframe>, and the
 * BROWSER fetches the PDF and shows it with its own viewer.
 * Example: "http://localhost:8000/emails/01_invoice_front_range_provisions/attachments/FRP-INV-2026-1184.pdf"
 */
export function attachmentUrl(name: string, filename: string): string {
  return `${API_BASE}/emails/${encodeURIComponent(name)}/attachments/${encodeURIComponent(filename)}`;
}

/**
 * Thrown when the server refuses a new run because a spending limit is reached (HTTP 429). The message
 * is the server's own, ready to show, e.g. "You've processed 30 emails in the last 2 hours, ...".
 * A class of its own, so the page can tell it apart from a real error (and stop "Process whole inbox").
 */
export class LimitError extends Error {}

/**
 * WHEN the person clicks "Process": POST /emails/{name}/process, then read the answer AS IT ARRIVES.
 *
 * The answer is a stream of Server-Sent Events (SSE): text messages separated by an empty line, e.g.
 *     event: step
 *     data: {"step": "classify", "label": "Claude classified it: booking (confidence 0.97)", "detail": {...}}
 *     <empty line>
 * For each complete message this function calls onEvent({ kind: "step", data: {...} }), so the page can
 * draw the line straight away, while the graph is still running on the server.
 *
 * Why not the browser's EventSource (made for SSE)? It can only send GET requests; starting a run is
 * a POST. So: fetch, then read the body piece by piece:
 *   response.body                    the answer's bytes, arriving over time (a ReadableStream)
 *   .pipeThrough(TextDecoderStream)  bytes -> text
 *   reader.read()                    waits for the next piece; { done: true } when the server is finished
 * A piece can end in the middle of a message, so text is collected in `buffer` and only complete
 * messages (up to an empty line) are taken out of it.
 */
export async function processEmail(name: string, onEvent: (event: StreamEvent) => void): Promise<void> {
  const response = await fetch(`${API_BASE}/emails/${encodeURIComponent(name)}/process`, {
    method: "POST",
    headers: visitorHeaders(),
  });
  if (response.status === 429) {
    // The demo's spending limit (step 18): the server explains which one in `detail`.
    const body = (await response.json()) as { detail: string };
    throw new LimitError(body.detail);
  }
  if (!response.ok || response.body === null) {
    throw new Error(`${response.status} ${response.statusText} when starting the run`);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    // Take out every complete message ("...\n\n") now in the buffer; keep the unfinished rest.
    let end = buffer.indexOf("\n\n");
    while (end !== -1) {
      const message = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      onEvent(parseMessage(message));
      end = buffer.indexOf("\n\n");
    }
  }
}

/**
 * One SSE message -> a StreamEvent. Example:
 *   'event: step\ndata: {"step": "classify", ...}'  ->  { kind: "step", data: { step: "classify", ... } }
 */
function parseMessage(message: string): StreamEvent {
  let kind = "";
  let data = "";
  for (const line of message.split("\n")) {
    if (line.startsWith("event: ")) kind = line.slice("event: ".length);
    if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  return { kind, data: JSON.parse(data) } as StreamEvent;
}

// --- The decision (step 16.3) -----------------------------------------------------------------------

/** A message as it was finally sent (after approve or edit). Same fields as the draft. */
export type OutgoingMessage = {
  kind: string;
  outgoing_to: string;
  outgoing_subject: string;
  outgoing_body: string;
  reason: string;
};

/**
 * One run as the server sees it (GET /runs/{id}, or the answer to a decision). Examples:
 *   waiting:  { thread_id: "...", status: "waiting", approval_request: { ...draft + evidence... }, decision: null, sent: null, steps: [] }
 *   finished: { thread_id: "...", status: "finished", approval_request: null, decision: "approve",
 *               sent: { outgoing_to: "Front Range Provisions <...>", ... },
 *               steps: [{ step: "approval", ... }, { step: "action", ... }] }   (steps: only in a decision's answer)
 * After a reject, `sent` is null: nothing went out.
 */
export type RunView = {
  thread_id: string;
  status: "waiting" | "finished";
  approval_request: ApprovalRequest | null;
  decision: "approve" | "edit" | "reject" | null;
  sent: OutgoingMessage | null;
  steps: StepEvent[];
};

/**
 * What the person decided: the body of POST /runs/{id}/decision (the backend's HumanDecision).
 *   { decision: "approve" }
 *   { decision: "edit", edited_body: "Dear ...", edited_subject: "Re: ..." }
 *   { decision: "reject" }
 */
export type DecisionRequest = {
  decision: "approve" | "edit" | "reject";
  edited_body?: string;
  edited_subject?: string;
  comment?: string;
};

/** WHEN the person reopens an email that was processed before (e.g. after a reload): GET /runs/{id}. */
export function fetchRun(threadId: string): Promise<RunView> {
  return getJson<RunView>(`/runs/${encodeURIComponent(threadId)}`);
}

/**
 * WHEN the person clicks Approve, Send edited or Reject: POST /runs/{id}/decision. The server resumes
 * the paused run (approval -> action) and answers with the finished run and its last steps.
 */
export async function sendDecision(threadId: string, decision: DecisionRequest): Promise<RunView> {
  const response = await fetch(`${API_BASE}/runs/${encodeURIComponent(threadId)}/decision`, {
    method: "POST",
    // The body is JSON, so the server must be told: Content-Type: application/json
    headers: { ...visitorHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(decision),         // JSON.stringify (JavaScript): object -> JSON text
  });
  if (response.status === 409) {
    // 409 Conflict = the run is no longer waiting: it was already decided (e.g. a second click, or
    // another tab). Not an error for the person: load the run as it really is and show that.
    return fetchRun(threadId);
  }
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: the decision was not accepted`);
  }
  return (await response.json()) as RunView;
}

// --- The Sent folder (step 16.4) --------------------------------------------------------------------

/**
 * One decision recorded by the action node (a row of the `actions` table, this visitor's only). Example:
 *   { thread_id: "31917ec5-...", email_name: "03_booking_complete", decision: "edit", kind: "reply_to_sender",
 *     outgoing_to: "Sarah Mitchell <sarah.mitchell@mail.example>", outgoing_subject: "Re: Room availability ...",
 *     outgoing_body: "Dear Sarah Mitchell, ...", comment: "", decided_at: "2026-11-13T13:00:41.5+00:00" }
 * A rejected draft has a row too (decision "reject"): the Sent folder leaves those out.
 */
export type SentItem = {
  thread_id: string;
  email_name: string;
  decision: "approve" | "edit" | "reject";
  kind: string;
  outgoing_to: string;
  outgoing_subject: string;
  outgoing_body: string;
  comment: string;
  decided_at: string;
};

/** WHEN the person opens the Sent tab: GET /sent -> this visitor's decisions, newest first. */
export function fetchSent(): Promise<SentItem[]> {
  return getJson<SentItem[]>("/sent");
}
