"""Single-line query parser: one input box -> značka + court.

``parse_query`` accepts free text ("sp. zn. 41 C 12/2024-58 Okresní soud
Brno-venkov", "KSBR 41 INS 1234/2024") or a URL (InfoSoud, ISIR, own site).
"""

from __future__ import annotations

import re
from datetime import date
from dataclasses import dataclass, replace
from typing import Mapping, Optional

from .client import SpisZn, parse_spis_zn
from .court_match import CODE_RE, ISIR_COURT_CODES, known_courts, resolve_court
from .query_urls import UrlCase, extract_url_case, is_url

NO_SPZN_MSG = "Nepodařilo se najít spisovou značku. Zadejte např. „41 C 12/2024“."

_SPZN_RE = re.compile(
    r"(?<![\d/])(\d+)\s*((?:[A-Za-z]+[\s.]+)*[A-Za-z]+)\s*(\d+)\s*[/_]\s*(\d{4}|\d{2})(?!\d)"
    r"(?:\s*-\s*(\d+)(?!\d))?"
)
# Značka bez lomítka ("1T682025" = 1 T 68/2025): ročník = poslední 4 číslice ve tvaru 19xx/20xx.
_SPZN_NOSEP_RE = re.compile(
    r"(?<![\d/])(\d+)\s*((?:[A-Za-z]+[\s.]+)*[A-Za-z]+)\s*(\d{1,7}?)\s?((?:19|20)\d{2})(?![\d/])"
)
_PARTIAL_RE = re.compile(r"(?<![\d/])(\d+)\s*([A-Za-z]+(?:\s+[A-Za-z]+)*)?\s*(\d+)?\s*(?:[/_]\s*(\d*))?")
_PREFIX_RE = re.compile(
    r"(?<!\w)(?:sp\.?\s*zn\.?|č\.?\s*j\.?|čj\.?|spisov[áa]\s+zna[čc]ka)(?![^\W\d_])",
    re.IGNORECASE,
)
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_PUNCT_RE = re.compile(r"[,;:()\[\]\"„“]+")


@dataclass(frozen=True)
class ParsedQuery:
    spis_zn: SpisZn
    court_code: Optional[str]
    cislo_listu: Optional[int]
    is_insolvency: bool
    source: str
    court_hint: Optional[str]


def normalize_input(text: str) -> str:
    """Unify whitespace (incl. nbsp) and dash characters."""
    return " ".join(text.replace(" ", " ").translate(_DASHES).split())


def full_year(year: str) -> int:
    """2-digit years: 00-79 -> 20xx, 80-99 -> 19xx."""
    if len(year) == 4:
        return int(year)
    value = int(year)
    return 2000 + value if value < 80 else 1900 + value


def _build_spis_zn(senat, druh, bc, rocnik) -> SpisZn:
    druh = " ".join(druh.replace(".", " ").split())
    return parse_spis_zn(f"{senat} {druh} {bc}/{rocnik}")


def _clean_remainder(before: str, after: str) -> str:
    joined = _PREFIX_RE.sub(" ", f"{before} {after}")
    return " ".join(_PUNCT_RE.sub(" ", joined).split())


def _is_insolvency(spis_zn: SpisZn) -> bool:
    return spis_zn.druh_veci.upper() == "INS"


def _validated_code(raw: Optional[str], court_map) -> Optional[str]:
    """Accept a code only if known (court_map given) or code-shaped (no map)."""
    if not raw:
        return None
    code = ISIR_COURT_CODES.get(raw.upper(), raw.upper())
    if court_map is None:
        return code if code == "NS" or CODE_RE.match(code) else None
    return code if code in known_courts(court_map) else None


def _finish(spis_zn, court_code, cislo_listu, source, hint) -> ParsedQuery:
    code = court_code or spis_zn.court_code  # keeps NS auto-detection
    return ParsedQuery(
        spis_zn=replace(spis_zn, court_code=code),
        court_code=code,
        cislo_listu=cislo_listu,
        is_insolvency=_is_insolvency(spis_zn),
        source=source,
        court_hint=hint,
    )


def _match_spzn(text: str):
    """(match, senát, druh, číslo, ročník, číslo listu) – nejdřív s lomítkem, pak bez něj."""
    m = _SPZN_RE.search(text)
    if m:
        return (m, *m.groups())
    m = _SPZN_NOSEP_RE.search(text)
    if m and _plausible_year(int(m.group(4))):
        return (m, *m.groups(), None)
    return None


def _plausible_year(year: int) -> bool:
    return 1990 <= year <= date.today().year + 1


def _parse_text(text: str, court_map: Optional[Mapping[str, str]]) -> ParsedQuery:
    found = _match_spzn(text)
    if not found:
        raise ValueError(NO_SPZN_MSG)
    m, senat, druh, bc, yy, listu = found
    spis_zn = _build_spis_zn(senat, druh, bc, full_year(yy))
    remainder = _clean_remainder(text[: m.start()], text[m.end():])
    code = resolve_court(remainder, court_map) if remainder else None
    return _finish(spis_zn, code, int(listu) if listu else None, "text", remainder or None)


def _spis_zn_from_url(case: UrlCase) -> tuple:
    """(SpisZn, text-court-hint) from URL fields."""
    if case.spis_zn_text:
        inner = _parse_text(normalize_input(case.spis_zn_text), None)
        return inner.spis_zn, inner.court_hint
    if case.rocnik is None or case.bc_vec is None or case.druh_veci is None:
        raise ValueError("V odkazu se nepodařilo najít spisovou značku.")
    senat = case.cislo_senatu or "0"
    return _build_spis_zn(senat, case.druh_veci, case.bc_vec, full_year(case.rocnik)), None


def _parse_url(text: str, court_map: Optional[Mapping[str, str]]) -> ParsedQuery:
    case = extract_url_case(text)
    try:
        spis_zn, inner_hint = _spis_zn_from_url(case)
    except ValueError as exc:
        raise ValueError(f"Z odkazu se nepodařilo získat spisovou značku: {exc}") from exc
    raw = case.court_raw or inner_hint
    code = _validated_code(raw, court_map)
    if code is None and raw and not CODE_RE.match(raw.upper()):
        code = resolve_court(raw, court_map)
    return _finish(spis_zn, code, None, case.source, raw)


def parse_query(text: str, court_map: Optional[Mapping[str, str]] = None) -> ParsedQuery:
    """Parse a one-line query into značka + court. Raises ValueError (Czech)."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError(NO_SPZN_MSG)
    cleaned = normalize_input(text)
    if is_url(cleaned):
        return _parse_url(cleaned, court_map)
    return _parse_text(cleaned, court_map)


def explain_query(text: str, court_map: Optional[Mapping[str, str]] = None) -> dict:
    """Co se z (neúplného) dotazu podařilo rozpoznat – pro nápovědu pod vyhledávacím polem.

    Vrací {"senat", "druh", "cislo", "rocnik", "court_code", "missing": [...]}; chybějící části jsou None.
    """
    cleaned = _PREFIX_RE.sub(" ", normalize_input(text or ""))
    m = _PARTIAL_RE.search(cleaned)
    senat = druh = cislo = rocnik = None
    rest = cleaned
    if m:
        senat, druh, cislo, rocnik = m.group(1), m.group(2), m.group(3), m.group(4) or None
        rest = (cleaned[: m.start()] + " " + cleaned[m.end():]).strip()
        if druh and court_map is not None and resolve_court(druh, court_map) and not cislo:
            rest, druh = f"{druh} {rest}".strip(), None  # "1 Děčín" – slovo je soud, ne druh věci
    court = resolve_court(rest, court_map) if rest else None
    missing = [name for name, val in (("senát", senat), ("druh věci", druh), ("číslo", cislo), ("ročník", rocnik))
               if not val]
    return {"senat": senat, "druh": druh, "cislo": cislo, "rocnik": rocnik,
            "court_code": court, "court_hint": rest or None, "missing": missing}
