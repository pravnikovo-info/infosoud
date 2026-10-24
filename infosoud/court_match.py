"""Resolve free-text court references (names, locatives, codes) to court codes.

Pure functions, no network access. ``court_map`` is ``code -> official name``
(see ``InfoSoudClient.build_court_map``); built-in courts from ``client`` are
always added as a fallback.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping, Optional

from .client import EXTRA_COURTS, HISTORICAL_COURTS, KS_CODES

# ISIR (insolvency register) abbreviation -> InfoSoud court code.
# Note: KSOL -> KSSEMOC is deliberately NOT passed through
# COURT_CODE_ALIASES (which would turn it into KSSEMOS = Ostrava).
ISIR_COURT_CODES = {
    "KSPH": "KSSTCAB", "MSPH": "MSPHAAB", "KSBR": "KSJIMBM",
    "KSOS": "KSSEMOS", "KSOL": "KSSEMOC", "KSPA": "KSVYCPA",
    "KSLB": "KSSCELB", "KSUL": "KSSCEUL", "KSCB": "KSJICCB",
    "KSHK": "KSVYCHK", "KSPL": "KSZPCPM",
}

# Normalised (no diacritics, lowercase) common aliases -> code.
_ALIASES = {
    "ks hk": "KSVYCHK", "ns cr": "NS", "nscr": "NS", "ns brno": "NS",
    "nejvyssi soud cr": "NS", "ms praha": "MSPHAAB", "ms v praze": "MSPHAAB",
}

CODE_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3,8}$")

_NOISE = {"v", "ve", "pro", "soud", "u", "na"}
# query/name token -> (court type group, tie-break priority)
_TYPES = {
    "okresni": "os", "obvodni": "os", "os": "os",
    "mestsky": "ms", "ms": "ms",
    "krajsky": "ks", "ks": "ks",
    "vrchni": "vs", "vs": "vs",
    "nejvyssi": "ns", "ns": "ns",
}
_PRIORITY = {"os": 0, "ms": 1, "ks": 2, "vs": 3, "ns": 4}
_SUFFIXES = ("ich", "ych", "ech", "ach", "ami", "emi", "ym", "im", "em", "om",
             "ou", "u", "i", "y", "a", "e", "o")
_ALTERNATIONS = (("ze", "ha"), ("ce", "ka"), ("se", "cha"))  # Praze -> Praha


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def normalize(text: str) -> str:
    """Lowercase, no diacritics, parenthesised notes dropped, single spaces."""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = strip_diacritics(text).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def known_courts(court_map: Optional[Mapping[str, str]]) -> dict:
    """Built-in courts overlaid with the caller's map."""
    return {**KS_CODES, **EXTRA_COURTS, **HISTORICAL_COURTS, **(court_map or {})}


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            word = word[: -len(suffix)]
            break
    return word[:1] + word[1:].replace("e", "")


def _variants(word: str) -> frozenset:
    if word.isdigit():
        return frozenset({word})
    forms = {word}
    for ending, repl in _ALTERNATIONS:
        if word.endswith(ending):
            forms.add(word[: -len(ending)] + repl)
    return frozenset(_stem(f) for f in forms)


def _split(text: str) -> tuple:
    """(type group or None, core tokens) of a normalised string."""
    court_type = None
    core = []
    for token in normalize(text).split():
        if token in _TYPES:
            court_type = court_type or _TYPES[token]
        elif token not in _NOISE:
            core.append(token)
    return court_type, tuple(core)


def _covers(query_core: tuple, name_core: tuple) -> bool:
    name_forms = [_variants(t) for t in name_core]
    return all(any(_variants(q) & n for n in name_forms) for q in query_core)


def _type_ok(query_type: Optional[str], code: str, name_type: Optional[str]) -> bool:
    if query_type is None:
        return True
    return name_type == query_type or (query_type == "os" and code.startswith("OS"))


def _rank(courts: Mapping[str, str], query_type, query_core) -> list:
    """Sorted (unmatched-name-tokens, type priority, code, name) candidates."""
    ranked = []
    for code, name in courts.items():
        name_type, name_core = _split(name)
        if not _type_ok(query_type, code, name_type) or not _covers(query_core, name_core):
            continue
        priority = _PRIORITY.get(name_type or "os", 0)
        ranked.append((len(name_core) - len(query_core), priority, code, normalize(name)))
    return sorted(ranked)


def match_name(text: str, courts: Mapping[str, str]) -> Optional[str]:
    """Match a court name in any common form; None if unknown or ambiguous."""
    alias = _ALIASES.get(normalize(text))
    if alias and alias in courts:
        return alias
    query_type, query_core = _split(text)
    if not query_core and query_type != "ns":
        return None
    ranked = _rank(courts, query_type, query_core)
    if not ranked:
        return None
    best = [r for r in ranked if r[:2] == ranked[0][:2]]
    if len({r[3] for r in best}) > 1:
        return None  # genuinely different courts tie
    preferred = [r for r in best if r[2] in KS_CODES]
    return (preferred or best)[0][2]  # same name, several codes: canonical first


def match_code_token(token: str, courts: Mapping[str, str]) -> Optional[str]:
    """Return the court code for a code-looking token (ISIR abbr. included)."""
    code = token.upper()
    if code in ISIR_COURT_CODES:
        return ISIR_COURT_CODES[code]
    if code in courts:
        return code
    return None


def resolve_court(text: str, court_map: Optional[Mapping[str, str]]) -> Optional[str]:
    """Resolve a court code, ISIR abbreviation or (locative) name to a code."""
    courts = known_courts(court_map)
    tokens = (text or "").split()
    if not tokens:
        return None
    if len(tokens) == 1:
        return match_code_token(tokens[0], courts) or match_name(text, courts)
    for token in tokens:
        if CODE_RE.match(token) or token in ISIR_COURT_CODES:
            found = match_code_token(token, courts)
            if found:
                return found
    return match_name(text, courts)
