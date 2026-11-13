/**
 * The inbox list (left column, "Inbox" tab).
 *
 * WHAT HAPPENS: App gives this component the 10 rows (from GET /emails) and which one is selected.
 * It draws one button per email; when the person clicks one, it calls `onSelect(name)`, and App
 * takes it from there (loads the email, shows it in the middle).
 *
 * React terms:
 *  - A component is a function that returns what to draw (JSX: HTML-like tags inside TypeScript).
 *  - Props = the inputs a component receives from its parent, here `emails`, `selected`, `onSelect`.
 *  - `key` on a repeated element: React's id for each row, so it updates only rows that changed.
 */

// OURS:
import type { EmailStatus, EmailSummary } from "../api";
import { displayName, shortDate } from "../format";

// The badge text and colour (a CSS class) for each status.
const BADGE: Record<EmailStatus, { text: string; className: string }> = {
  new: { text: "New", className: "badge-new" },
  waiting: { text: "Waiting for approval", className: "badge-waiting" },
  approve: { text: "Approved", className: "badge-done" },
  edit: { text: "Edited & approved", className: "badge-done" },
  reject: { text: "Rejected", className: "badge-rejected" },
};

type Props = {
  emails: EmailSummary[];
  selected: string | null;               // the name of the selected email, null = none yet
  running: string | null;                // the email being processed right now, if any
  onSelect: (name: string) => void;      // called with the clicked email's name
};

export function Inbox({ emails, selected, running, onSelect }: Props) {
  return (
    <ul className="mail-list">
      {/* .map (JavaScript): one <li> per email, in the order the backend sent them (oldest first). */}
      {emails.map((email) => {
        const badge = email.name === running ? { text: "Processing…", className: "badge-running" } : BADGE[email.status];
        return (
          <li key={email.name}>
            <button
              className={email.name === selected ? "inbox-row selected" : "inbox-row"}
              onClick={() => onSelect(email.name)}
            >
              <span className="inbox-top">
                <span className="inbox-sender">{displayName(email.sender)}</span>
                <span className="inbox-date">{shortDate(email.date)}</span>
              </span>
              <span className="inbox-subject">{email.subject}</span>
              <span className={`badge ${badge.className}`}>{badge.text}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
