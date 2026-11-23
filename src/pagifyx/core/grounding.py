"""Checks that a generated plan states no number or email the website and the form do not contain.

Copy may be generated freely. Numbers, prices, and contact details are facts, so each one must
appear in the source text. A failed check raises ValueError, which triggers the model's retry.
"""

import re
from collections.abc import Iterable

from pagifyx.core.models import Overview

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _normal_numbers(text: str) -> set[str]:
    """Digits only, so '1,000', '1.000', and '1000' compare equal."""
    return {re.sub(r"[.,]", "", number) for number in _NUMBER.findall(text)}


def unsupported_details(overview: Overview, sources: Iterable[str]) -> list[str]:
    """Numbers and email addresses in the plan's text that no source contains."""
    source_text = " ".join(sources)
    known_numbers = _normal_numbers(source_text)
    known_emails = {email.lower() for email in _EMAIL.findall(source_text)}
    missing: list[str] = []
    for panel in overview.panels:
        text = f"{panel.headline} {panel.body}"
        missing.extend(sorted(_normal_numbers(text) - known_numbers))
        missing.extend(email for email in _EMAIL.findall(text) if email.lower() not in known_emails)
    return missing


def check_grounding(overview: Overview, sources: Iterable[str]) -> None:
    """Raise ValueError when the plan states a number or email that no source contains."""
    missing = unsupported_details(overview, sources)
    if missing:
        listed = ", ".join(dict.fromkeys(missing))
        raise ValueError(f"Remove details that are not on the website or in the form: {listed}.")
