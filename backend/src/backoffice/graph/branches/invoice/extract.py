"""Invoice branch, node 1: copy the invoice into a form (ONE LLM call). Plus the code that turns the
printed amounts into exact numbers.

In:   state["email"]   the incoming email; its PDF attachment is already Markdown (read_email, Docling)
Out:  {"invoice_extraction": InvoiceExtraction(...)}   what the LLM READ, exactly as printed

    PDF ──Docling (read_email)──► Markdown table ──Claude Haiku──► InvoiceExtraction (text, as printed)
                                                                        │
                                          parse_amount / to_invoice_lines (code, used by check_invoice)
                                                                        ▼
                                                  InvoiceLine with exact Decimals (services/invoice_check.py)

The LLM only COPIES: amounts come back as the printed text ("4.60", "$1,795.50"). Code converts
them, and the check (11.2) redoes every multiplication and sum, so a model's arithmetic is never
trusted.

Run it on a demo invoice (from backend/):
    uv run python -m backoffice.graph.branches.invoice.extract 01_invoice_front_range_provisions
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import sys                                     # sys.argv: the words typed on the command line
from decimal import Decimal, InvalidOperation  # exact numbers; InvalidOperation = "this text isn't a number"
from pathlib import Path                       # Path: a file path you can join with /

# Langfuse (tracing):
from langfuse import observe                   # @observe: record this function as a named step in the trace

# OURS:
from backoffice.graph.state import EmailState, InvoiceExtraction, ParsedEmail
from backoffice.llm import anthropic_client                        # the shared Claude client
from backoffice.services.invoice_check import InvoiceLine
from backoffice.tracing import init_tracing

# The Langfuse client must exist before the first @observe-decorated call (see tracing.py).
init_tracing()

# Claude Haiku 5.5: copying a table into a form. If the real runs show it misreading, this is
# the one line to change (decided per step, CLAUDE.md "Open decisions").
EXTRACT_MODEL = "claude-haiku-5-5"

# extract.py is at backoffice/graph/branches/invoice/ -> three levels up is backoffice/.
SYSTEM_PROMPT = (Path(__file__).resolve().parents[3] / "prompts" / "invoice_extract_system.md").read_text(encoding="utf-8")


def build_prompt(email: ParsedEmail) -> str:
    """
    The email and its whole attachment (the invoice as Markdown), between <email> tags (data,
    never instructions). Unlike classify, which sees a 1,500-character preview, extraction needs
    every line of the invoice.

    Example (#2, shortened):
        <email>
        From: Summit Linen & Laundry <accounts@summitlinen.example>
        Subject: Your invoice SLL-10442 (Oct 19-25)

        Hi Overlook team, Attached is this week's invoice ...

        Attachment: SLL-10442.pdf
        ## Summit Linen &amp; Laundry ...
        | Code   | Item laundered   |   Pieces | Price per piece   | Line total   |
        | SLL-01 | Queen flat sheet |      480 | $1.10             | $528.00      | ...
        </email>
    """
    parts = [f"From: {email.sender}", f"Subject: {email.subject}", "", email.body]
    for attachment in email.attachments:
        parts += ["", f"Attachment: {attachment.filename}", attachment.markdown]
    return "<email>\n" + "\n".join(parts) + "\n</email>"


# @observe (Langfuse): a named step "ask_llm_to_extract_invoice" in the trace; the Claude call inside it is
# recorded automatically (see tracing.py).
@observe(name="ask_llm_to_extract_invoice", capture_input=False)
def ask_llm_to_extract_invoice(email: ParsedEmail) -> InvoiceExtraction:
    """
    One call to Claude Haiku; returns the filled-in form (see InvoiceExtraction in state.py).
    messages.parse(..., output_format=InvoiceExtraction): same technique as classify.py.
    """
    response = anthropic_client().messages.parse(
        model=EXTRACT_MODEL,
        max_tokens=4096,                       # room for 5-20 lines of an invoice
        output_config={"effort": "low"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(email)}],
        output_format=InvoiceExtraction,
    )
    # No valid form: step 13 will turn this into "send to a human" instead of an error.
    if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
        raise RuntimeError(f"Invoice extraction failed: stop_reason={response.stop_reason}")
    return response.parsed_output


def extract_invoice(state: EmailState) -> dict:
    """
    THE NODE.
        in:  {..., "email": ParsedEmail(subject="Invoice FRP-INV-2026-1184 - The Overlook Hotel", attachments=[...])}
        out: {"invoice_extraction": InvoiceExtraction(supplier_name="Front Range Provisions", lines=[... 5 ...], ...)}
    """
    email = state["email"]
    # Step 13: an invoice that couldn't be read (read_email kept it with a read_error) or no PDF at
    # all: there is nothing to extract. Stop with a clear error; the invoice subgraph's error
    # handler turns it into a note to the front desk, WITH the email's sender, subject and text.
    #   e.g. "The attached invoice FRP-INV-2026-1184.pdf could not be read (ConversionError: ...)"
    pdfs = [a for a in email.attachments if a.content_type == "application/pdf"]
    unreadable = [a for a in pdfs if a.read_error]
    if unreadable:
        first = unreadable[0]
        raise RuntimeError(f"The attached invoice {first.filename} could not be read ({first.read_error})")
    if not pdfs:
        raise RuntimeError("The email has no PDF invoice attached")
    return {"invoice_extraction": ask_llm_to_extract_invoice(email)}


# --- From printed text to exact numbers (code; used by check_invoice in checks.py) ---------------

def parse_amount(text: str | None) -> Decimal | None:
    """
    A printed amount -> an exact Decimal; None if it isn't a number.
        "4.60" -> Decimal("4.60")   "$1,795.50" -> Decimal("1795.50")   "30" -> Decimal("30")
        "" / None / "two" -> None
    """
    if text is None:
        return None
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned) if cleaned else None
    except InvalidOperation:
        return None


def to_invoice_lines(extraction: InvoiceExtraction) -> tuple[list[InvoiceLine], list[str | None], list[str]]:
    """
    Turn the LLM's lines (text) into InvoiceLine objects (Decimals) for the checks.

    Returns three lists:
      lines      the lines that could be read, as InvoiceLine
      doubts     for each of those lines, what the MODEL wasn't sure about (status unclear/missing +
                 its reason), or None
      unreadable lines whose quantity or amounts aren't numbers (or are negative), with why

    Shape returned (#1):
        ([InvoiceLine(code="FRP-1021", description="Mozz. LM WM, 6x5 lb", quantity=Decimal("30"), unit="LB",
                      unit_price=Decimal("4.60"), line_total=Decimal("138.00")),
          ... 4 more ...],
         [None, None, "No item number printed.", None, None],
         [])
    """
    lines: list[InvoiceLine] = []
    doubts: list[str | None] = []
    unreadable: list[str] = []
    for extracted in extraction.lines:
        quantity = parse_amount(extracted.quantity)
        unit_price = parse_amount(extracted.unit_price)
        line_total = parse_amount(extracted.line_total)
        if None in (quantity, unit_price, line_total) or min(quantity, unit_price, line_total) < 0:
            unreadable.append(f"{extracted.description}: quantity {extracted.quantity!r}, unit price "
                              f"{extracted.unit_price!r}, amount {extracted.line_total!r} can't all be read as numbers")
            continue
        lines.append(InvoiceLine(code=extracted.code or None, description=extracted.description, quantity=quantity,
                                 unit=extracted.unit_of_measure, unit_price=unit_price, line_total=line_total))
        doubts.append(None if extracted.status == "ok" else (extracted.reason or f"status {extracted.status}"))
    return lines, doubts, unreadable


# Command line (plain Python; see main_graph.py for `if __name__ == "__main__":` and sys.argv).
if __name__ == "__main__":
    from backoffice.graph.main_graph import email_path_for          # ours: email name -> safe path
    from backoffice.graph.nodes.read_email import parse_eml        # ours: .eml -> ParsedEmail
    from backoffice.tracing import flush_traces

    for name in sys.argv[1:] or ["01_invoice_front_range_provisions"]:
        extraction = ask_llm_to_extract_invoice(parse_eml(email_path_for(name)))
        print(f"=== {name}: {extraction.supplier_name}, {extraction.invoice_number}, {extraction.invoice_date}")
        for line in extraction.lines:
            print(f"  {line.code or '(no code)':<9} {line.description:<34} qty {line.quantity:>5} {line.unit_of_measure:<6}"
                  f" @ {line.unit_price:>7} = {line.line_total:>8}  {line.status}  {line.reason}")
        print(f"  subtotal {extraction.subtotal}   tax {extraction.tax}   total {extraction.total}")
    flush_traces()
