"""InfoSoud API client — Czech court case tracking (infosoud.gov.cz).

Public REST API of the Czech Ministry of Justice for looking up
court case status, events timeline, and scheduled hearings.

No authentication required. Be polite — use reasonable delays between requests.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://infosoud.gov.cz/api/v1"

# Universal regex — tolerant to any whitespace/separator combo
_SPZN_UNIVERSAL = re.compile(
    r"(\d+)\s*([A-Za-z]+)\s*(\d+)\s*[/_]\s*(\d{4})"
    r"(?:\s+([A-Z][A-Z0-9]{4,9}))?$"
)


@dataclass(frozen=True)
class SpisZn:
    """Parsed spisová značka (Czech court case file number)."""
    cislo_senatu: int
    druh_veci: str
    bc_vec: int
    rocnik: int
    court_code: str | None = None

    def to_api_params(self, court_code: str | None = None) -> dict:
        """Convert to InfoSoud API request body."""
        code = court_code or self.court_code
        params = {
            "cisloSenatu": str(self.cislo_senatu),
            "druhVeci": self.druh_veci,
            "bcVec": str(self.bc_vec),
            "rocnik": str(self.rocnik),
        }
        if code:
            code = resolve_court_code(code)
            ct = classify_court_code(code)
            if ct == "NS":
                params["typOrganizace"] = "NEJVYSSI"
            elif ct in ("KS", "VS", "MS"):
                params["druhOrganizace"] = code
            else:
                params["okresniSoud"] = code
        return params

    def canonical(self) -> str:
        """Canonical form: '1 T 64/2024'."""
        return f"{self.cislo_senatu} {self.druh_veci} {self.bc_vec}/{self.rocnik}"

    def compact(self) -> str:
        """Compact form: '1T64_2024'."""
        return f"{self.cislo_senatu}{self.druh_veci}{self.bc_vec}_{self.rocnik}"

    def __str__(self) -> str:
        s = self.canonical()
        if self.court_code:
            s += f" {self.court_code}"
        return s


def parse_spis_zn(text: str) -> SpisZn:
    """Parse spisová značka in any common format.

    Extremely tolerant — whitespace and separators are ignored.
    All of these parse identically:
        "1 T 64/2024"       "1T64/2024"        "1T 64/2024"
        "1 T64/2024"        "1T64_2024"        "1 T 64 / 2024"
        "43T191_2024"       "43 T 191/2024 OSPHA09"
        "11 C 233/2022"     "2 To 29/2023"     "6To436/2025"
    """
    text = text.strip()
    m = _SPZN_UNIVERSAL.match(text)
    if m:
        return SpisZn(
            cislo_senatu=int(m.group(1)),
            druh_veci=m.group(2),
            bc_vec=int(m.group(3)),
            rocnik=int(m.group(4)),
            court_code=m.group(5) if m.group(5) else None,
        )
    raise ValueError(f"Cannot parse spisová značka: {text!r}")


# --- Court codes ---

KS_CODES = {
    "KSJIMBM": "Krajský soud Brno",
    "KSJICCB": "Krajský soud České Budějovice",
    "KSVYCHK": "Krajský soud Hradec Králové",
    "KSSEMOS": "Krajský soud Ostrava",
    "KSZPCPM": "Krajský soud Plzeň",
    "KSSTCAB": "Krajský soud Praha",
    "KSSCEUL": "Krajský soud Ústí nad Labem",
    "MSPHAAB": "Městský soud Praha",
    "VSSEMOL": "Vrchní soud Olomouc",
    "VSPHAAB": "Vrchní soud Praha",
}

EXTRA_COURTS = {
    "KSVYCPA": "Krajský soud Hradec Králové — pobočka Pardubice",
    "KSSEMOC": "Krajský soud Ostrava — pobočka Olomouc",
    "KSSCELB": "Krajský soud Ústí nad Labem — pobočka Liberec",
    "VSSTCAB": "Vrchní soud Praha",
    "VSSEMOC": "Vrchní soud Olomouc",
    "OSSEMHA": "Okresní soud Karviná — pobočka Havířov",
    "OSSEMKR": "Okresní soud Bruntál — pobočka Krnov",
    "OSSEMVM": "Okresní soud Vsetín — pobočka Valašské Meziříčí",
}

COURT_CODE_ALIASES = {
    "KSSEMOC": "KSSEMOS",
    "VSSTCAB": "VSPHAAB",
}

PRAGUE_DISTRICTS = [f"OSPHA{i:02d}" for i in range(1, 11)]

EVENT_LABELS = {
    "ZAHAJ_RIZ": "Zahájení řízení",
    "NAR_JED": "Nařízení jednání",
    "ZRUS_JED": "Zrušení jednání",
    "VYD_ROZH": "Vydání rozhodnutí",
    "ODES_SPIS": "Odeslání spisu",
    "VRAC_SPIS": "Vrácení spisu",
    "POD_OP_PR": "Podání opravného prostředku",
    "VYR_OP_PR": "Vyřízení opravného prostředku",
    "ODVOLANI": "Řízení o odvolání",
    "DOVOL_RIZ": "Řízení o dovolání",
    "NAD_RIZENI": "Řízení u nadřízeného soudu",
    "ST_VEC_ODS": "Skončení věci",
    "ST_VEC_OBZ": "Obživnutí věci",
    "ST_VEC_PRE": "Přerušení řízení",
    "ST_VEC_UPR": "Ukončení přerušení",
    "ST_VEC_VYR": "Vyřízení věci",
    "ST_VEC_PUK": "Pravomocné ukončení",
    "SPIS_K_SC": "Spis odeslán soudci",
    "SPIS_K_SO": "Spis odeslán soudnímu komisaři",
    "SPIS_OD_SC": "Soudce předal spis",
    "SPIS_OD_SO": "Soudní komisař předal spis",
    "PREVD_SPIS": "Převedeno pod jinou sp. zn.",
    "PR_VEC_NS": "Přerušení věci",
    "VR_SP_NS": "Vrácení spisu odvolacímu soudu",
}


def classify_court_code(code: str) -> str:
    """Classify court code: NS, KS, VS, MS, or OS."""
    if not code:
        return "OS"
    upper = code.upper()
    for prefix in ("NS", "VS", "MS", "KS"):
        if upper.startswith(prefix):
            return prefix
    return "OS"


def resolve_court_code(code: str) -> str:
    """Resolve alternative court codes to InfoSoud codes."""
    return COURT_CODE_ALIASES.get(code.upper(), code)


def strip_diacritics(text: str) -> str:
    """Remove Czech diacritics for fuzzy matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


class InfoSoudClient:
    """Client for the InfoSoud REST API.

    Usage::

        client = InfoSoudClient()
        case = client.search_case("1 T 64/2024", "OSSCEDC")
        hearings = client.search_hearings("1 T 64/2024", "OSSCEDC")
        courts = client.build_court_map()
    """

    def __init__(self, delay: float = 0.5, timeout: int = 15,
                 base_url: str = BASE_URL):
        self.base_url = base_url
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "infosoud-oss/0.1 (https://github.com/pravnikovo/infosoud)",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        self._throttle()
        url = f"{self.base_url}{path}"
        t0 = time.monotonic()
        resp = self.session.get(url, params=params, timeout=self.timeout)
        self._last_request = time.monotonic()
        elapsed_ms = int((self._last_request - t0) * 1000)
        logger.debug("GET %s → %d (%dms)", path, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        self._throttle()
        url = f"{self.base_url}{path}"
        t0 = time.monotonic()
        resp = self.session.post(url, json=body, timeout=self.timeout)
        self._last_request = time.monotonic()
        elapsed_ms = int((self._last_request - t0) * 1000)
        logger.debug("POST %s → %d (%dms)", path, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        return resp.json()

    def search_case(self, spis_zn: str | SpisZn,
                    court_code: str | None = None) -> dict:
        """Search case by spisová značka. Returns events timeline."""
        if isinstance(spis_zn, str):
            spis_zn = parse_spis_zn(spis_zn)
        code = court_code or spis_zn.court_code

        if code and code.upper() in ("OSPHA", "OSPHA0"):
            return self._search_prague(spis_zn, "/rizeni/vyhledej")

        return self._post("/rizeni/vyhledej", spis_zn.to_api_params(court_code))

    def search_hearings(self, spis_zn: str | SpisZn,
                        court_code: str | None = None) -> dict:
        """Search hearings for a case."""
        if isinstance(spis_zn, str):
            spis_zn = parse_spis_zn(spis_zn)
        code = court_code or spis_zn.court_code

        if code and code.upper() in ("OSPHA", "OSPHA0"):
            return self._search_prague(spis_zn, "/jednani/vyhledej",
                                       extra={"typHledani": "SPZN"})

        params = spis_zn.to_api_params(court_code)
        params["typHledani"] = "SPZN"
        return self._post("/jednani/vyhledej", params)

    def get_event_detail(self, spis_zn: str | SpisZn,
                         court_code: str | None,
                         event_type: str, event_order: int) -> dict:
        """Fetch detail for a single event (room, time, result)."""
        if isinstance(spis_zn, str):
            spis_zn = parse_spis_zn(spis_zn)
        params = spis_zn.to_api_params(court_code)
        params["druhUdalosti"] = event_type
        params["poradiUdalosti"] = str(event_order)
        return self._post("/udalost/vyhledej", params)

    def get_courts(self) -> list[dict]:
        """Get list of krajské/vrchní soudy."""
        return self._get("/organizace/lov")

    def get_district_courts(self, ks_code: str | None = None) -> list[dict]:
        """Get list of okresní soudy, optionally filtered by KS."""
        params = {"kod": ks_code} if ks_code else None
        return self._get("/organizace/podrizene/lov", params=params)

    def build_court_map(self) -> dict[str, str]:
        """Fetch and build complete court code → name mapping."""
        result = dict(EXTRA_COURTS)
        for court in self.get_courts():
            result[court["kod"]] = court["nazev"]
        for court in self.get_district_courts():
            result[court["kod"]] = court["nazev"]
        return result

    def resolve_court_name(self, name: str,
                           court_map: dict | None = None) -> str | None:
        """Fuzzy-match a court name (diacritics-insensitive) to a court code."""
        if court_map is None:
            court_map = self.build_court_map()
        name_lower = strip_diacritics(name.lower())
        for prefix in ("os ", "okresni soud ", "krajsky soud ", "ks ", "ms "):
            if name_lower.startswith(prefix):
                name_lower = name_lower[len(prefix):]
                break
        best_code, best_score = None, 0
        for code, full_name in court_map.items():
            full_lower = strip_diacritics(full_name.lower())
            if name_lower in full_lower:
                score = len(name_lower) / len(full_lower)
                if score > best_score:
                    best_score = score
                    best_code = code
        return best_code

    def _search_prague(self, spis_zn: SpisZn, path: str,
                       extra: dict | None = None) -> dict:
        """Try all Prague districts for an ambiguous OSPHA code."""
        for district in PRAGUE_DISTRICTS:
            params = spis_zn.to_api_params(district)
            if extra:
                params.update(extra)
            try:
                result = self._post(path, params)
                if result.get("udalosti") or result.get("stav"):
                    logger.info("Resolved OSPHA → %s for %s",
                                district, spis_zn.canonical())
                    return result
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 400:
                    continue
                raise
        raise ValueError(
            f"Cannot find {spis_zn.canonical()} in any Prague district court"
        )
