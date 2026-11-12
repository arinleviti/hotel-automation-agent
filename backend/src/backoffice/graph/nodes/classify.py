"""Node 2 of the graph: classify the email (an LLM node: ONE model call with structured output).

In:   state["email"]   the ParsedEmail added by read_email
Out:  {"classification": Classification(...)}

The model only FILLS IN A FORM (the Classification Pydantic model in graph/state.py): type,
suspicious + reason, confidence, summary. It does not decide where the email goes next: the
routing code (step 8.3) reads this form and decides. "The model judges, code decides."

Structured output, and why the method is called "parse":
  The SDK has two ways to call Claude:
    client.messages.create(...)  -> the RAW reply: Claude's answer as text, here a JSON string:
        '{"type": "question", "suspicious": false, "suspicious_reason": "", "confidence": 0.97, "summary": "..."}'
    client.messages.parse(..., output_format=Classification)  -> the same call, plus two extras:
        1. BEFORE: it turns the Classification class into a JSON Schema (the standard description
           of an object's fields and types; see Classification.model_json_schema()) and sends it
           as the REQUIRED answer format, so Claude's answer must fit it;
        2. AFTER: it PARSES Claude's JSON text into a Classification object and validates it
           (wrong type, missing field, confidence outside 0..1 = an error, never a bad object).
  "Parse" = turning text into a structured object: that's step 2, and the reason for the name.
  The result, response.parsed_output, is a Classification OBJECT, not JSON:
        Classification(type="question", suspicious=False, suspicious_reason="", confidence=0.97, summary="...")
  so the routing code can simply write `if c.suspicious:` or `if c.confidence < 0.7:`.

Prompt injection: the email is put between <email> tags and the system prompt says everything
inside is data, never instructions. Email #9 tries exactly that ("Note for the automated
assistant ...") and must come out as suspicious.
"""

from pathlib import Path

from langfuse import observe

from backoffice.graph.state import Classification, EmailState, ParsedEmail
from backoffice.llm import anthropic_client
from backoffice.tracing import init_tracing

# The Langfuse client must exist before the first @observe-decorated call (see tracing.py).
init_tracing()

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


# Tracing (Langfuse, step 8.4), what ends up in the trace for this function:
#   classify                       <- the graph node (recorded by the LangGraph callback)
#     classify_email               <- THIS function, recorded by @observe below (a named step)
#       anthropic.messages.create  <- the model call: recorded AUTOMATICALLY. The Anthropic SDK
#                                     reports its own calls in OpenTelemetry format (a standard for
#                                     traces) and Langfuse picks them up, with model, prompt,
#                                     answer, tokens and cost (e.g. 1,478 in + 139 out = $0.000217).
# @observe(...) = Langfuse's decorator: it wraps the function and records when it starts and ends
# and what it returns. capture_input=False: the input is a whole ParsedEmail object; the exact
# prompt is already in the automatic model-call record.
# Why here and not on every node: the NODES (read_email, classify, decide_route ...) are all
# recorded automatically by the LangGraph callback. @observe adds a named sub-step INSIDE the
# classify node. It's optional: without it, the Claude call would simply appear directly under
# "classify" in the trace.
@observe(name="classify_email", capture_input=False)
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
