/**
 * The selected email, as a mail program shows it: From / To / Date / Subject, the body, and each
 * attached PDF.
 *
 * WHAT HAPPENS: App gives this component the email (from GET /emails/{name}). For each attachment
 * it shows the file name; clicking "Show" opens the PDF right here in an <iframe> (a small window
 * inside the page). The iframe's address is GET /emails/{name}/attachments/{file}: the browser
 * fetches the PDF and draws it with its own PDF viewer, so the page needs no PDF library.
 *
 * React terms:
 *  - useState (React): a value the component remembers between redraws; changing it redraws.
 *    Here: which attachments are open, e.g. { "FRP-INV-2026-1184.pdf": true }.
 */

// React:
import { useState } from "react";

// OURS:
import { attachmentUrl, type EmailDetail } from "../api";
import { fileSize, longDate } from "../format";

type Props = {
  email: EmailDetail;
};

export function EmailView({ email }: Props) {
  // Shape: { "FRP-INV-2026-1184.pdf": true }  (missing = closed)
  const [open, setOpen] = useState<Record<string, boolean>>({});

  return (
    <article className="email">
      <h1 className="email-subject">{email.subject}</h1>
      <dl className="email-headers">
        <dt>From</dt>
        <dd>{email.sender}</dd>
        <dt>To</dt>
        <dd>{email.to}</dd>
        <dt>Date</dt>
        <dd>{longDate(email.date)}</dd>
      </dl>

      {/* white-space: pre-wrap (CSS, class email-body): keep the email's own line breaks. */}
      <div className="email-body">{email.body}</div>

      {email.attachments.map((file) => (
        <section className="attachment" key={file.filename}>
          <div className="attachment-bar">
            <span className="attachment-icon" aria-hidden="true">PDF</span>
            <span className="attachment-name">{file.filename}</span>
            <span className="attachment-size">{fileSize(file.size)}</span>
            <button
              className="link-button"
              // {...open, [name]: !open[name]} (JavaScript): a copy of `open` with this one file flipped.
              onClick={() => setOpen({ ...open, [file.filename]: !open[file.filename] })}
            >
              {open[file.filename] ? "Hide" : "Show"}
            </button>
          </div>
          {open[file.filename] && (
            <iframe
              className="attachment-viewer"
              title={file.filename}
              src={attachmentUrl(email.name, file.filename)}
            />
          )}
        </section>
      ))}
    </article>
  );
}
