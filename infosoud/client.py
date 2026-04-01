"""InfoSoud API client — Czech court case tracking (infosoud.gov.cz)."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://infosoud.gov.cz/api/v1"
CACHE_TTL_CASE = 6 * 3600      # 6 hours for case events
CACHE_TTL_HEARINGS = 3600       # 1 hour for hearings

# Universal regex — tolerant to any whitespace/separator combo
# Captures: (číslo senátu)(druh věci)(běžné číslo)(ročník) + optional court code
# Works with: "1 T 64/2024", "1T64_2024", "1T 64 / 2024", "1 T64/2024", etc.
# Druh věci specific to Nejvyšší soud (auto-detected, no court code needed)
_NS_DRUHY = {"CDO", "ODO", "TDO", "TZ", "NCU", "TKCDO", "NSCR", "ICM"}

_SPZN_UNIVERSAL = re.compile(
    r"(\d+)\s*([A-Za-z]+)\s*(\d+)\s*[/_]\s*(\d{4})"
    r"(?:\s+([A-Z][A-Z0-9]{4,9}))?$"
)


@dataclass(frozen=True)
class SpisZn:
    """Parsed spisová značka."""
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
            court_type = classify_court_code(code)
            if court_type == "NS":
                params["typOrganizace"] = "NEJVYSSI"
            elif court_type in ("KS", "VS", "MS"):
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
        druh = m.group(2)
        court = m.group(5) if m.group(5) else None
        # Auto-detect Nejvyšší soud from druh věci (CDO, ODO, TDO, TZ, NCU)
        if not court and druh.upper() in _NS_DRUHY:
            court = "NS"
        return SpisZn(
            cislo_senatu=int(m.group(1)),
            druh_veci=druh,
            bc_vec=int(m.group(3)),
            rocnik=int(m.group(4)),
            court_code=court,
        )

    raise ValueError(f"Cannot parse spisová značka: {text!r}")


# --- Court code mapping (InfoSoud org codes) ---

# Krajské / Vrchní soudy (from /organizace/lov)
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

def classify_court_code(code: str) -> str:
    """Classify court code into type: NS, KS, VS, MS, OS.

    Handles ambiguous codes like 'OSPHA' (Praha without district number).
    For 'OSPHA' + two-letter suffix codes like 'OSPHA03', returns 'OS'.
    For KS/VS/MS prefixed codes, returns the prefix type.
    """
    if not code:
        return "OS"
    upper = code.upper()
    if upper.startswith("NS"):
        return "NS"
    if upper.startswith("VS"):
        return "VS"
    if upper.startswith("MS"):
        return "MS"
    if upper.startswith("KS"):
        return "KS"
    return "OS"


# Prague district court expansion: OSPHA → try all 10 districts
PRAGUE_DISTRICTS = [f"OSPHA{i:02d}" for i in range(1, 11)]

# Caseflow/iSpis code → InfoSoud code mapping (where they differ)
COURT_CODE_ALIASES = {
    "KSSEMOC": "KSSEMOS",   # KS Ostrava — caseflow uses "OC", InfoSoud uses "OS"
    "VSSTCAB": "VSPHAAB",   # VS Praha — caseflow uses STC, InfoSoud uses PHA
}

# Courts not returned by InfoSoud LOV but valid in API (pobočky, vrchní soudy)
EXTRA_COURTS = {
    # Nejvyšší soud
    "NS": "Nejvyšší soud",
    # Pobočky KS
    "KSVYCPA": "Krajský soud Hradec Králové — pobočka Pardubice",
    "KSSEMOC": "Krajský soud Ostrava — pobočka Olomouc",
    "KSSCELB": "Krajský soud Ústí nad Labem — pobočka Liberec",
    # Vrchní soudy (LOV returns them under different codes)
    "VSSTCAB": "Vrchní soud Praha",
    "VSSEMOC": "Vrchní soud Olomouc",
    # Pobočky OS
    "OSSEMHA": "Okresní soud Karviná — pobočka Havířov",
    "OSSEMKR": "Okresní soud Bruntál — pobočka Krnov",
    "OSSEMVM": "Okresní soud Vsetín — pobočka Valašské Meziříčí",
}

# Historical courts (zrušené, easter egg — visible in whisperer but not functional)
HISTORICAL_COURTS = {
    "OSJIMLH": "Okresní soud v Luhačovicích (zrušen)",
    "OSJIMVI": "Okresní soud ve Vizovicích (zrušen)",
    "OSSEMBH": "Okresní soud v Bohumíně (zrušen)",
    "OSJIMJR": "Okresní soud v Jaroslavicích (zrušen)",
    "OSSEMOD": "Okresní soud v Odrách (zrušen)",
}


def resolve_court_code(code: str) -> str:
    """Resolve caseflow court code to InfoSoud code."""
    return COURT_CODE_ALIASES.get(code.upper(), code)


class InfoSoudClient:
    """Client for the InfoSoud REST API."""

    def __init__(self, delay: float = 0.5, timeout: int = 15):
        self.base_url = BASE_URL
        self.delay = delay
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "rejstriky/0.1 (Czech public register lookup)",
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

    # --- Public API methods ---

    def search_case(self, spis_zn: str | SpisZn,
                    court_code: str | None = None) -> dict:
        """Search case by spisová značka. Returns events timeline.

        For ambiguous codes like 'OSPHA' (Praha without district),
        tries all Prague districts until a match is found.
        """
        if isinstance(spis_zn, str):
            spis_zn = parse_spis_zn(spis_zn)
        code = court_code or spis_zn.court_code

        # Handle ambiguous Prague OS codes
        if code and code.upper() in ("OSPHA", "OSPHA0"):
            return self._search_prague(spis_zn, "/rizeni/vyhledej")

        params = spis_zn.to_api_params(court_code)
        return self._post("/rizeni/vyhledej", params)

    def search_hearings(self, spis_zn: str | SpisZn,
                        court_code: str | None = None) -> dict:
        """Search hearings for a case. Returns scheduled hearings."""
        if isinstance(spis_zn, str):
            spis_zn = parse_spis_zn(spis_zn)
        code = court_code or spis_zn.court_code

        if code and code.upper() in ("OSPHA", "OSPHA0"):
            return self._search_prague(spis_zn, "/jednani/vyhledej",
                                       extra={"typHledani": "SPZN"})

        params = spis_zn.to_api_params(court_code)
        params["typHledani"] = "SPZN"
        return self._post("/jednani/vyhledej", params)

    def _search_prague(self, spis_zn: SpisZn, path: str,
                       extra: dict | None = None) -> dict:
        """Try all Prague districts for an ambiguous OSPHA code."""
        for district in PRAGUE_DISTRICTS:
            params = spis_zn.to_api_params(district)
            if extra:
                params.update(extra)
            try:
                result = self._post(path, params)
                # If we got data (not an error), we found the right district
                if result.get("udalosti") or result.get("stav"):
                    logger.info("Resolved OSPHA → %s for %s",
                                district, spis_zn.canonical())
                    return result
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 400:
                    continue
                raise
        raise ValueError(
            f"Cannot find {spis_zn.canonical()} in any Prague district court "
            f"(tried OSPHA01-OSPHA10)"
        )

    def get_event_detail(self, spis_zn: str | SpisZn,
                         court_code: str | None,
                         event_type: str, event_order: int) -> dict:
        """Fetch detail for a single event (udalost/vyhledej).

        Returns atributy with room, time, result etc.
        """
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
        """Fetch and build complete court code → name mapping.

        Includes pobočky and courts not returned by the LOV endpoint.
        """
        result = dict(EXTRA_COURTS)
        result.update(HISTORICAL_COURTS)
        for court in self.get_courts():
            result[court["kod"]] = court["nazev"]
        for court in self.get_district_courts():
            result[court["kod"]] = court["nazev"]
        return result


# --- Event type labels ---

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
    "SPIS_K_SC": "Spis odeslán soudci",
    "SPIS_K_SO": "Spis odeslán soudnímu komisaři",
    "SPIS_OD_SC": "Soudce předal spis",
    "SPIS_OD_SO": "Soudní komisař předal spis",
    "PREVD_SPIS": "Převedeno pod jinou sp. zn.",
    "PR_VEC_NS": "Přerušení věci",
    "VR_SP_NS": "Vrácení spisu odvolacímu soudu",
}


def format_case_summary(data: dict) -> str:
    """Format case data into human-readable summary."""
    lines = []
    org = data.get("organizace", "?")
    nadr = data.get("nadrizenaOrganizace", "")
    stav = data.get("stav", "?")
    stav_datum = data.get("stavDatum", "")

    spzn = f"{data.get('cislo', '') or ''} {data.get('druh', '') or ''} {data.get('bcVec', '') or ''}/{data.get('rocnik', '') or ''}"
    lines.append(f"Sp. zn.: {spzn}")
    lines.append(f"Soud: {org}" + (f" ({nadr})" if nadr else ""))
    lines.append(f"Stav: {stav}" + (f" (od {stav_datum})" if stav_datum else ""))

    platne_k = data.get("platneK", "")
    if platne_k:
        lines.append(f"Platné k: {platne_k[:10]}")

    events = data.get("udalosti", [])
    if events:
        lines.append(f"\nUdálosti ({len(events)}):")
        for ev in events:
            code = ev.get("udalost", "?")
            label = EVENT_LABELS.get(code, code)
            datum = ev.get("datum", "?")
            zruseno = " [ZRUŠENO]" if ev.get("zruseno") else ""
            znacka_id = ev.get("znackaId", {})
            # Show related sp.zn. if different from main
            related = ""
            if (znacka_id.get("organizace") != data.get("typOrganizace") or
                    znacka_id.get("bcVec") != data.get("bcVec") or
                    znacka_id.get("druhVeci") != data.get("druh")):
                rel_zn = f"{znacka_id.get('cisloSenatu', '') or ''} {znacka_id.get('druhVeci', '') or ''} {znacka_id.get('bcVec', '') or ''}/{znacka_id.get('rocnik', '') or ''}"
                rel_org = znacka_id.get("organizace", "")
                if rel_org and rel_org != data.get("typOrganizace"):
                    related = f" → {rel_zn} {rel_org}"
            lines.append(f"  {datum}  {label}{zruseno}{related}")

    navazne = data.get("navazneVeci", [])
    if navazne:
        lines.append(f"\nNavazné věci:")
        for nv in navazne:
            nv_zn = f"{nv.get('cisloSenatu', '') or ''} {nv.get('druhVeci', '') or ''} {nv.get('bcVec', '') or ''}/{nv.get('rocnik', '') or ''}"
            lines.append(f"  {nv_zn} {nv.get('organizace', '')}")

    return "\n".join(lines)


def format_hearings_summary(data: dict) -> str:
    """Format hearings data into human-readable summary."""
    lines = []
    org = data.get("organizace", "?")
    lines.append(f"Jednání — {org}")

    events = data.get("udalosti", [])
    if not events:
        lines.append("  Žádná jednání nařízena.")
        return "\n".join(lines)

    for ev in events:
        datum = ev.get("datum", "?")
        cas = ev.get("cas", "?")
        druh = ev.get("druhJednani", "?")
        resitel = ev.get("resitel", "?")
        sin = ev.get("jednaciSin", "?")
        zruseno = " [ZRUŠENO]" if ev.get("jednaniZruseno") else ""
        lines.append(f"  {datum} {cas}  {druh}{zruseno}")
        lines.append(f"    Soudce: {resitel}")
        lines.append(f"    Síň: {sin}")

    return "\n".join(lines)
