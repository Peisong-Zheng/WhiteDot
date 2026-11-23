"""Immediate, offline corrections for known English typos and a few unambiguous phrases."""
from bisect import bisect_left
from functools import cache
import gzip
from pathlib import Path
import re

from .types import Issue


@cache
def _rows() -> list[bytes]:
    # The upstream CSV is sorted by the misspelling. Binary search needs no
    # index construction and keeps the first keystroke inexpensive.
    with gzip.open(Path(__file__).with_name("assets") / "english-typos.csv.gz", "rb") as data:
        return data.read().splitlines()


_CHUNK = re.compile(r"```[\s\S]*?(?:```|\Z)|`[^`\n]*(?:`|(?=\n)|\Z)|[^\s`]+")
_WORD = re.compile(r"\w+(?:['’]\w+)*")
_DOTTED = re.compile(r"\w\.\w")
_SENTENCE_BREAK = re.compile(r"[.!?\n]")
_REPEATS = frozenset("a an and at by for from in of on or the to with".split())
_CONTRACTIONS = {
    form.replace("'", ""): form for form in (
        "aren't", "couldn't", "didn't", "doesn't", "don't", "hadn't", "hasn't",
        "haven't", "isn't", "mustn't", "shouldn't", "wasn't", "weren't", "wouldn't",
    )
}
_THIRD_PERSON = {"are": "is", "am": "is", "have": "has", "go": "goes", "do": "does", "don't": "doesn't"}
_PLURAL = {"is": "are", "am": "are", "has": "have", "goes": "go", "does": "do", "doesn't": "don't"}
_AGREEMENT = {
    "i": {"is": "am", "are": "am", "has": "have", "goes": "go", "does": "do", "doesn't": "don't"},
    "he": _THIRD_PERSON, "she": _THIRD_PERSON, "it": _THIRD_PERSON,
    "we": _PLURAL, "you": _PLURAL, "they": _PLURAL,
}
_MAX_ISSUES = 128


def _spellings(word: str) -> tuple[str, ...]:
    if word in _CONTRACTIONS:
        return (_CONTRACTIONS[word],)
    needle = word.encode("ascii") + b","
    rows = _rows()
    pos = bisect_left(rows, needle)
    if pos < len(rows) and rows[pos].startswith(needle):
        return tuple(rows[pos][len(needle):].decode("utf-8").split(",")[:3])
    return ()


def check_local(text: str) -> list[Issue]:
    """Return corrections in source order, with offsets in Python characters."""
    issues = []
    previous = None
    previous_word = ""
    sentence_subject = None
    for chunk in _CHUNK.finditer(text):
        value = chunk.group()
        if (value.startswith("`") or "/" in value or "\\" in value or "@" in value
                or "#" in value or "_" in value or _DOTTED.search(value)):
            previous = None
            sentence_subject = None
            continue

        for match in _WORD.finditer(text, chunk.start(), chunk.end()):
            start, end = match.span()
            raw = match.group()
            word = raw.lower().replace("’", "'")
            gap = text[previous.end():start] if previous else ""
            begins_sentence = previous is None or bool(_SENTENCE_BREAK.search(gap))
            adjacent = bool(previous and gap.isspace() and not begins_sentence)
            if adjacent and sentence_subject and word in _AGREEMENT[sentence_subject] and raw.islower():
                replacement = _AGREEMENT[sentence_subject][word]
                if "’" in raw:
                    replacement = replacement.replace("'", "’")
                issues.append(Issue(start, end, raw, (replacement,), "Use the verb form that agrees with the subject."))
            elif (adjacent and word == previous_word and word in _REPEATS and raw.islower()
                  and (not issues or issues[-1].end <= previous.start())):
                first = previous.start()
                issues.append(Issue(first, end, text[first:end], (previous.group(),), "Remove the repeated word."))
            elif word.isascii() and word.isalpha() and (raw.islower() or (begins_sentence and raw.istitle())):
                choices = _spellings(word)
                if choices:
                    if raw.istitle():
                        choices = tuple(choice.capitalize() for choice in choices)
                    issues.append(Issue(start, end, raw, choices, "Check the spelling of this word."))

            if len(issues) >= _MAX_ISSUES:
                return issues
            sentence_subject = word if begins_sentence and word in _AGREEMENT else None
            previous = match
            previous_word = word
    return issues
