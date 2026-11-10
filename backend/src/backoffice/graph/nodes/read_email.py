"""Node 1 of the graph: read the .eml file (a CODE-ONLY node: no LLM).

In:   state["email_path"]  e.g. "C:/.../data/emails/01_invoice_front_range_provisions.eml"
Out:  {"email": ParsedEmail(...)}   (LangGraph merges this into the state)

What it does:
  1. opens the .eml with Python's built-in `email` module (the same module that built the files);
  2. takes the headers (from, to, subject, date ...) and the plain-text body;
  3. turns every PDF attachment into Markdown with Docling, so later nodes (the invoice extractor)
     can read the invoice as text, tables included.
"""

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from backoffice.graph.state import Attachment, EmailState, ParsedEmail
from backoffice.rag.parsing import parse_bytes


def parse_eml(path: Path) -> ParsedEmail:
    """
    Read one .eml file into our ParsedEmail.

    BytesParser(policy=policy.default).parse(file) is the standard way to read an email file:
    `policy.default` makes it return an EmailMessage (the modern API) with headers already decoded.
    The result behaves like a dictionary of headers: msg["Subject"], msg["From"] ...

    Shape returned (email #1):
        ParsedEmail(sender="Front Range Provisions <billing@frontrangeprovisions.example>",
                    to="The Overlook Hotel <info@overlook-hotel.example>",
                    subject="Invoice FRP-INV-2026-1184 - The Overlook Hotel",
                    date=datetime(2026, 10, 30, 16, 12, tzinfo=-06:00),
                    body="Hello,\n\nPlease find attached invoice FRP-INV-2026-1184 ...",
                    attachments=[Attachment(filename="FRP-INV-2026-1184.pdf", content_type="application/pdf",
                                            markdown="FRONT RANGE PROVISIONS ... | Item # | Description | ...")],
                    message_id="<...@frontrangeprovisions.example>", in_reply_to=None)
    """
    with path.open("rb") as file:                       # "rb" = read the raw bytes
        msg = BytesParser(policy=policy.default).parse(file)
    assert isinstance(msg, EmailMessage)                # policy.default always gives an EmailMessage

    # get_body(...) finds the main text part of the email; preferencelist=("plain",) = plain text,
    # not HTML. get_content() returns it as a Python string, already decoded.
    body_part = msg.get_body(preferencelist=("plain",))
    body = body_part.get_content() if body_part is not None else ""

    # The Date header becomes a datetime: msg["Date"].datetime (None if the header is missing).
    date_header = msg["Date"]
    date = date_header.datetime if date_header is not None else None

    return ParsedEmail(
        sender=str(msg["From"] or ""),
        to=str(msg["To"] or ""),
        subject=str(msg["Subject"] or ""),
        date=date,
        body=body.strip(),
        attachments=[read_attachment(part) for part in msg.iter_attachments()],
        message_id=str(msg["Message-ID"] or ""),
        in_reply_to=str(msg["In-Reply-To"]) if msg["In-Reply-To"] else None,
    )


def read_attachment(part: EmailMessage) -> Attachment:
    """
    One attachment -> Attachment. PDFs are converted to Markdown with Docling (tables kept as
    Markdown tables); other file types keep an empty text for now.

    part.get_content() gives the attachment's bytes (the email stores them encoded as text, base64;
    the email module decodes them back).
    """
    filename = part.get_filename() or "attachment"
    content_type = part.get_content_type()             # e.g. "application/pdf"
    markdown = ""
    if content_type == "application/pdf":
        markdown = parse_bytes(filename, part.get_content()).export_to_markdown()
    return Attachment(filename=filename, content_type=content_type, markdown=markdown)


def read_email(state: EmailState) -> dict:
    """
    THE NODE. LangGraph calls it with the whole state; it returns only what it adds.

    Example:
        in:  {"email_path": ".../06_question_pool_and_spa.eml"}
        out: {"email": ParsedEmail(subject="Pool and spa question", ...)}
    """
    return {"email": parse_eml(Path(state["email_path"]))}
