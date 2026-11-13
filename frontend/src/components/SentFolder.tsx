/**
 * The Sent folder (left column, "Sent" tab): what went out after a person approved it.
 *
 * WHAT HAPPENS: App loads this visitor's decisions (GET /sent: the `actions` table, newest first) and
 * gives them to this component, which lists the ones that were SENT (approved or edited; rejected
 * drafts never left, so they are not here: their inbox badge says "Rejected"). Clicking a row opens
 * the original email: the middle shows it, the right column shows the message that was sent.
 *
 * Example row:   To: Front Range Provisions                     2:41 PM
 *                Re: Invoice FRP-INV-2026-1184 - The Overlook Hotel
 *                [Reply to the sender]  [edited]
 */

// OURS:
import type { SentItem } from "../api";
import { displayName } from "../format";

// How each kind of message is named (DraftKind in the backend).
const KIND_NAME: Record<string, string> = {
  reply_to_sender: "Reply to the sender",
  ok_to_pay: "OK to pay (Accounts)",
  forward_to_staff: "Forwarded to a person",
};

type Props = {
  items: SentItem[];
  selected: string | null;
  onSelect: (emailName: string) => void;     // opens the ORIGINAL email (e.g. "03_booking_complete")
};

export function SentFolder({ items, selected, onSelect }: Props) {
  const sent = items.filter((item) => item.decision !== "reject");
  if (sent.length === 0) {
    return <p className="empty list-empty">Nothing sent yet. Approve a draft and it appears here.</p>;
  }
  return (
    <ul className="mail-list">
      {sent.map((item) => (
        <li key={item.thread_id}>
          <button
            className={item.email_name === selected ? "inbox-row selected" : "inbox-row"}
            onClick={() => onSelect(item.email_name)}
          >
            <span className="inbox-top">
              <span className="inbox-sender">To: {displayName(item.outgoing_to)}</span>
              <span className="inbox-date">
                {new Date(item.decided_at).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}
              </span>
            </span>
            <span className="inbox-subject">{item.outgoing_subject}</span>
            <span className="sent-tags">
              <span className="badge badge-done">{KIND_NAME[item.kind] ?? item.kind}</span>
              {item.decision === "edit" && <span className="badge badge-new">edited</span>}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
