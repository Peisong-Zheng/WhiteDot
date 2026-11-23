"""Avoid submitting a field that visibly contains a common credential format."""
import re

_CREDENTIAL = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{24,}|"
    r"github_pat_[A-Za-z0-9_]{24,}|AIza[A-Za-z0-9_-]{30,}|"
    r"AKIA[A-Z0-9]{16})\b|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\b(?:authorization\s*:\s*bearer|(?:api[_ -]?key|password|access[_ -]?token)\s*[:=])"
    r"\s*[\x22\x27]?[A-Za-z0-9_/+=.-]{8,}", re.I,
)


def contains_credential(text):
    return _CREDENTIAL.search(text) is not None


def input_status(text, limit):
    if contains_credential(text):
        return "Remove the possible secret to check this draft."
    if len(text) > limit:
        return f"Check up to {limit:,} characters at a time."
    if not re.search("[a-zA-Z]", text):
        return "Enter English text to check."
    return ""
