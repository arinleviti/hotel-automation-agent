"""Node 2 of the graph: classify the email (an LLM node: ONE model call with structured output).

In:   state["email"]   the ParsedEmail added by read_email
Out:  {"classification": Classification(...)}

The model only FILLS IN A FORM (the Classification Pydantic model in graph/state.py): type,
suspicious + reason, confidence, summary. It does not decide where the email goes next: the
routing code (step 8.3) reads this form and decides. "The model judges, code decides."

Structured output: client.messages.parse(..., output_format=Classification) sends the
Classification model to Claude as the REQUIRED answer format and returns a validated
Classification object (response.parsed_output), so we never parse JSON by hand.

Prompt injection: the email is put between <email> tags and the system prompt says everything
inside is data, never instructions. Email #9 tries exactly that ("Note for the automated
assistant ...") and must come out as suspicious.
"""

from pathlib import Path

from backoffice.graph.state import Classification, EmailState, ParsedEmail
from backoffice.llm import anthropic_client

# Claude Haiku 5.5: decided in CLAUDE.md (sorting 10 short emails is a simple task).
CLASSIFY_MODEL = "claude-haiku-5-5"

# The instructions live in a separate file (prompts/), as agreed in the folder structure.
# classify.py is at backoffice/graph/nodes/ -> two levels up is backoffice/.
SYSTEM_PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "classify_system.md").read_text(encoding="utf-8")

# How much of an attachment the classifier sees: enough to recognise an invoice, not the whole file.
ATTACHMENT_PREVIEW_CHARS = 1500


def email_for_prompt(email: ParsedEmail) -> str:
    """
    How the email is shown to Claude.

    Example (email #2, shortened):
        <email>
        From: Summit Linen & Laundry <accounts@summitlinen.example>
        Subject: Your invoice SLL-10442 (Oct 19-25)
        Date: 2026-11-01 09:03:00-07:00

        Hi Overlook team,

        Attached is this week's invoice for linen service, Oct 19 to Oct 25. Thanks as always!
        ...
        Attachment: SLL-10442.pdf (application/pdf)
        ## Summit Linen & Laundry
        ...
        </email>
    """
    lines = [
        f"From: {email.sender}",
        f"Subject: {email.subject}",
        f"Date: {email.date}",
        "",
        email.body,
    ]
    for attachment in email.attachments:
        lines += ["", f"Attachment: {attachment.filename} ({attachment.content_type})",
                  attachment.markdown[:ATTACHMENT_PREVIEW_CHARS]]
    return "<email>\n" + "\n".join(lines) + "\n</email>"


def classify_email(email: ParsedEmail) -> Classification:
    """
    One call to Claude Haiku; returns the filled-in form.

    Shape returned (email #9):
        Classification(type="booking", suspicious=True,
                       suspicious_reason="It contains instructions addressed to the automated assistant ...",
                       confidence=0.85, summary="Guest confirms a Dec 5-7 stay and claims a free suite upgrade.")
    """
    response = anthropic_client().messages.parse(
        model=CLASSIFY_MODEL,
        max_tokens=2048,                         # room for brief thinking + the short form
        output_config={"effort": "low"},         # a simple task: think little, answer fast
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": email_for_prompt(email)}],
        output_format=Classification,            # the answer MUST match this Pydantic model
    )
    # stop_reason: "refusal" = the model declined; "max_tokens" = it ran out of room before
    # finishing the form. Either way there is no valid form. (Step 13 will turn this into
    # "send to a human" instead of an error.)
    if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
        raise RuntimeError(f"Classification failed: stop_reason={response.stop_reason}")
    return response.parsed_output


def classify(state: EmailState) -> dict:
    """
    THE NODE. Reads the email added by read_email, returns only what it adds.

    Example:
        in:  {"email_path": "...", "email": ParsedEmail(subject="Pool and spa question", ...)}
        out: {"classification": Classification(type="question", suspicious=False, confidence=0.97, ...)}
    """
    return {"classification": classify_email(state["email"])}
