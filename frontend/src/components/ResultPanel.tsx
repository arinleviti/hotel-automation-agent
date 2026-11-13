/**
 * The RIGHT column: what the agent drafted, why, and the person's decision.
 *
 * WHAT HAPPENS WHEN ...
 *  - the run is paused at approval:  show "Why this draft" (the reason + the evidence from the approval
 *    request), the draft, and three buttons: Approve & send / Edit / Reject.
 *  - the person clicks Edit:         the subject and body become text boxes; "Send edited" sends the
 *    new text as an "edit" decision, "Cancel" goes back.
 *  - the person decides:             App sends the decision (POST /runs/{id}/decision); the run resumes
 *    on the server (approval -> action) and this panel turns into the confirmation:
 *    "✓ Sent to Front Range Provisions" with the final text, or "✗ Rejected: nothing was sent".
 *
 * Evidence example (#1, the invoice):
 *   supplier  Front Range Provisions (agreed prices found)
 *   lines     ✗ FRP-1021  Mozz. LM WM, 6x5 lb   30 LB x $4.60 = $138.00   Price 4.60/LB, contract 4.25/lb
 *             ✓ FRP-1034  Butter unsalted 36x1 lb   20 LB x $4.10 = $82.00
 *             ⚠ (no code) Eggs large Gr.A 15 dz case   ...   No item number, ...
 *   outcome   correction_needed
 * Lines starting with ✓ / ⚠ / ✗ are coloured green / amber / red.
 */

// React:
import { useState } from "react";

// OURS:
import type { ApprovalRequest, DecisionRequest, OutgoingMessage } from "../api";

// How each kind of draft is named, and what "Approve" does with it (DraftKind in the backend).
const KIND: Record<string, { name: string; approve: string; done: string }> = {
  reply_to_sender: { name: "Reply to the sender", approve: "Approve & send", done: "Sent to" },
  ok_to_pay: { name: "Note to Accounts: OK to pay", approve: "Approve & send to Accounts", done: "Sent to" },
  forward_to_staff: { name: "Forward to a person", approve: "Approve & forward", done: "Forwarded to" },
};

type Props = {
  approval: ApprovalRequest | null;         // the paused run's request (null once decided)
  decision: string | null;                  // "approve" / "edit" / "reject" once decided
  sent: OutgoingMessage | null;             // what went out (null after a reject)
  onDecide: (decision: DecisionRequest) => Promise<void>;
};

export function ResultPanel({ approval, decision, sent, onDecide }: Props) {
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);              // true while the decision is being sent
  const [error, setError] = useState<string | null>(null);

  // --- Decided: the confirmation ------------------------------------------------------------------
  if (decision !== null) {
    if (decision === "reject" || sent === null) {
      return (
        <div className="outcome outcome-rejected">
          <div className="outcome-title">✗ Rejected: nothing was sent</div>
          <p>The decision is recorded. A person can now handle this email by hand.</p>
        </div>
      );
    }
    const kind = KIND[sent.kind] ?? KIND.reply_to_sender;
    return (
      <div className="outcome outcome-sent">
        <div className="outcome-title">
          ✓ {kind.done} {sent.outgoing_to}
          {decision === "edit" && <span className="outcome-note"> (edited by you)</span>}
        </div>
        <article className="draft">
          <dl className="email-headers">
            <dt>Subject</dt>
            <dd>{sent.outgoing_subject}</dd>
          </dl>
          <div className="email-body">{sent.outgoing_body}</div>
        </article>
        <p className="empty">Demo: recorded in the database, no real email was sent.</p>
      </div>
    );
  }

  if (approval === null) {
    return <p className="empty">The draft reply and its evidence will appear here once the email is processed.</p>;
  }

  // --- Waiting: evidence, draft, buttons ------------------------------------------------------------
  const draft = approval.outgoing_draft;
  const kind = KIND[draft.kind] ?? KIND.reply_to_sender;

  async function decide(request: DecisionRequest) {
    setBusy(true);
    setError(null);
    try {
      await onDecide(request);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function startEditing() {
    setSubject(draft.outgoing_subject);
    setBody(draft.outgoing_body);
    setEditing(true);
  }

  return (
    <div className="result">
      <section className="why">
        <h3 className="why-title">Why this draft</h3>
        {approval.reason_for_human_review && (
          <p className="why-human">Sent to a person: {approval.reason_for_human_review}</p>
        )}
        {draft.reason && <p>{draft.reason}</p>}
        <Evidence evidence={approval.evidence} />
      </section>

      <article className="draft">
        <div className="draft-kind">{kind.name}</div>
        <dl className="email-headers">
          <dt>To</dt>
          <dd>{draft.outgoing_to}</dd>
          <dt>Subject</dt>
          <dd>
            {editing ? (
              <input className="edit-subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
            ) : (
              draft.outgoing_subject
            )}
          </dd>
        </dl>
        {editing ? (
          // A controlled text box (React): its text lives in `body`; every key press updates it.
          <textarea className="edit-body" value={body} onChange={(e) => setBody(e.target.value)} />
        ) : (
          <div className="email-body">{draft.outgoing_body}</div>
        )}

        <div className="decision-bar">
          {editing ? (
            <>
              <button
                className="primary-button"
                disabled={busy || body.trim() === ""}
                onClick={() => decide({ decision: "edit", edited_body: body, edited_subject: subject })}
              >
                Send edited
              </button>
              <button className="secondary-button" disabled={busy} onClick={() => setEditing(false)}>
                Cancel
              </button>
            </>
          ) : (
            <>
              <button className="primary-button" disabled={busy} onClick={() => decide({ decision: "approve" })}>
                {kind.approve}
              </button>
              <button className="secondary-button" disabled={busy} onClick={startEditing}>
                Edit
              </button>
              <button className="reject-button" disabled={busy} onClick={() => decide({ decision: "reject" })}>
                Reject
              </button>
            </>
          )}
          {busy && <span className="empty">Resuming the run…</span>}
        </div>
        {error && <p className="decision-error">{error}</p>}
      </article>
    </div>
  );
}

/**
 * The evidence from the approval request: each key as a small heading, text as it is, lists one item
 * per line. Keys are made readable: "not_in_documents" -> "not in documents".
 */
function Evidence({ evidence }: { evidence: Record<string, unknown> }) {
  // Object.entries: [["supplier", "Front Range ..."], ["lines", ["✗ FRP-1021 ...", ...]], ...]; empty values skipped
  const entries = Object.entries(evidence).filter(
    ([, value]) => value !== "" && value !== null && !(Array.isArray(value) && value.length === 0),
  );
  if (entries.length === 0) return null;
  return (
    <dl className="evidence">
      {entries.map(([key, value]) => (
        <div className="evidence-row" key={key}>
          <dt>{key.replaceAll("_", " ")}</dt>
          <dd>
            {Array.isArray(value) ? (
              <ul>
                {value.map((item, index) => (
                  <li key={index} className={verdictClass(String(item))}>
                    {String(item).trim()}
                  </li>
                ))}
              </ul>
            ) : (
              <span className={verdictClass(String(value))}>{String(value)}</span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** "✗ FRP-1021 ..." -> "verdict-bad"; "⚠ ..." -> "verdict-warn"; "✓ ..." -> "verdict-ok"; else no colour. */
function verdictClass(text: string): string {
  const first = text.trim().charAt(0);
  if (first === "✗") return "verdict-bad";
  if (first === "⚠") return "verdict-warn";
  if (first === "✓") return "verdict-ok";
  return "";
}
