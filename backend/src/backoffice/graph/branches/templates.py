"""Reply templates shared by the branches that answer with fixed text (booking, invoice).

Moved here from booking/replies.py in step 11.3, when the invoice branch became the second user
(convention: a function moves to a shared module when a second module needs it).

=================================================================================================
HOW A TEMPLATE IS FILLED: string.Template (plain Python)
=================================================================================================
A template file in data/reply_templates/ has $placeholders:   Dear $guest_name, ... Total: $total
Template(text).substitute(values) replaces each $name with values["name"]:
    values = {"guest_name": "Sarah Mitchell", "total": "$1,440.72", ...}
    ->  Dear Sarah Mitchell, ... Total: $1,440.72
substitute (not safe_substitute): a $placeholder with no value RAISES an error, so nobody can ever
receive "Dear $guest_name" or a blank total. The dollar signs of prices come from code, inside the
VALUE ("$1,440.72"); a literal $ written in a template file would have to be $$.
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
from decimal import Decimal                    # exact money amounts
from pathlib import Path                       # Path: a file path you can join with /
from string import Template                    # fills $placeholders in a text

# templates.py is at backend/src/backoffice/graph/branches/ -> five levels up is the repo root.
TEMPLATES_DIR = Path(__file__).resolve().parents[5] / "data" / "reply_templates"


def render(template_name: str, values: dict[str, str]) -> str:
    """
    Read data/reply_templates/<template_name>.txt and fill its $placeholders.

    Example: render("booking_ask_missing", {"guest_name": "Tom", "missing_items": "  - how many ..."})
    Raises KeyError if the template uses a placeholder not in `values` (never a blank in an email).
    """
    text = (TEMPLATES_DIR / f"{template_name}.txt").read_text(encoding="utf-8")
    return Template(text).substitute(values)


def format_money(amount: Decimal) -> str:
    """Decimal("1440.72") -> "$1,440.72"   (",.2f" = thousands separator, 2 decimals)"""
    return f"${amount:,.2f}"


def bullet_list(lines: list[str]) -> str:
    """["how many children ...", "the age of ..."] -> "  - how many children ...\n  - the age of ..." """
    return "\n".join(f"  - {line}" for line in lines)


def reply_subject(incoming_subject: str) -> str:
    """"Room availability December 18-21" -> "Re: Room availability December 18-21" (no "Re: Re:")."""
    if incoming_subject.lower().startswith("re:"):
        return incoming_subject
    return f"Re: {incoming_subject}"
