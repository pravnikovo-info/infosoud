"""Extract case identifiers from InfoSoud / ISIR / own-site URLs.

Supported (all best effort, parameter names matched case-insensitively and
ignoring underscores):

* ``https://infosoud.gov.cz/detail-rizeni?...``  (new InfoSoud)
* ``https://infosoud.justice.cz/InfoSoud/public/search.do?...``  (legacy)
* ``https://isir.justice.cz/...`` with ``spis_znacka`` or ``druh_vec``,
  ``bc_vec``, ``rocnik``, ``cislo_senatu`` / ``id_senatu`` and optionally
  ``id_osoby_puvodce`` (court abbreviation)
* ``https://infosoud.pravnikovo.info/case?sp_zn=...&court_code=...``
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional
from urllib.parse import parse_qs, urlsplit

NO_CASE_MSG = "V odkazu se nepodařilo najít spisovou značku."


@dataclass(frozen=True)
class UrlCase:
    """Raw fields extracted from a URL (nothing validated yet)."""
    source: str
    spis_zn_text: Optional[str] = None   # full značka text (own / ISIR spis_znacka)
    cislo_senatu: Optional[str] = None
    druh_veci: Optional[str] = None
    bc_vec: Optional[str] = None
    rocnik: Optional[str] = None
    court_raw: Optional[str] = None      # code or ISIR abbreviation


def is_url(text: str) -> bool:
    return text.lower().startswith(("http://", "https://")) or "://" in text


def _params(query: str) -> dict:
    """Lower-cased, underscore-free keys -> first non-empty value."""
    result = {}
    for key, values in parse_qs(query, keep_blank_values=False).items():
        value = next((v.strip() for v in values if v.strip()), "")
        if value:
            result.setdefault(key.lower().replace("_", ""), value)
    return result


def _legacy_court(p: dict) -> Optional[str]:
    org = p.get("org")
    if org and org.upper().startswith("NS"):
        return "NS"
    return org or p.get("krajorg")


def _new_court(p: dict) -> Optional[str]:
    if p.get("typorganizace", "").upper() == "NEJVYSSI":
        return "NS"
    return p.get("okresnisoud") or p.get("druhorganizace")


def _from_fields(source: str, p: dict, court: Optional[str]) -> UrlCase:
    return UrlCase(
        source=source,
        cislo_senatu=p.get("cislosenatu") or p.get("idsenatu"),
        druh_veci=p.get("druhveci") or p.get("druhvec"),
        bc_vec=p.get("bcvec"),
        rocnik=p.get("rocnik"),
        court_raw=court,
    )


def extract_url_case(url: str) -> UrlCase:
    """Classify a URL and pull out its case fields; ValueError if unknown host."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    p = _params(parts.query)
    if "isir.justice.cz" in host:
        court = p.get("idosobypuvodce") or p.get("org")
        case = _from_fields("isir_url", p, court)
        return replace(case, spis_zn_text=p.get("spisznacka"))
    if "infosoud.justice.cz" in host or parts.path.endswith("search.do"):
        return _from_fields("infosoud_legacy_url", p, _legacy_court(p))
    if "infosoud.gov.cz" in host:
        return _from_fields("infosoud_url", p, _new_court(p))
    if "spzn" in p:
        return UrlCase(source="own_url", spis_zn_text=p["spzn"],
                       court_raw=p.get("courtcode"))
    raise ValueError(NO_CASE_MSG + " Podporované jsou odkazy InfoSoud, ISIR a pravnikovo.info.")
