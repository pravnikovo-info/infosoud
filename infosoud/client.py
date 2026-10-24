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

# Spaced form with multi-word druh: "3 P A NC 53/2026", "1 T 64/2024"
_SPZN_SPACED = re.compile(
    r"(\d+)\s+((?:[A-Za-z]+\s+)*[A-Za-z]+)\s+(\d+)\s*[/_]\s*(\d{4})"
    r"(?:\s+([A-Z][A-Z0-9]{4,9}))?$"
)
# Mixed/compact form: "1T64/2024", "1 T64/2024", "1T 64/2024", "1T64_2024"
# Also handles dot-separated multi-word druh: "3P.A.NC53_2026"
_SPZN_MIXED = re.compile(
    r"(\d+)\s*([A-Za-z]+(?:\.[A-Za-z]+)*)\s*(\d+)\s*[/_]\s*(\d{4})"
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
        """Compact form for URLs: '1T64_2024'.

        Multi-word druh věci uses dots: '3P.A.NC53_2026'.
        """
        druh = self.druh_veci.replace(" ", ".")
        return f"{self.cislo_senatu}{druh}{self.bc_vec}_{self.rocnik}"

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
    Multi-word druh věci is supported in spaced forms:
        "3 P A NC 53/2026"  "3 P A NC 53/2026 OSSTCKH"
    """
    text = text.strip()

    # Try spaced form first (handles multi-word druh), then mixed/compact
    for pattern in (_SPZN_SPACED, _SPZN_MIXED):
        m = pattern.match(text)
        if m:
            # Dots in compact form represent spaces: "P.A.NC" → "P A NC"
            druh = m.group(2).replace(".", " ")
            court = m.group(5) if m.group(5) else None
            # Auto-detect Nejvyšší soud from druh věci (CDO, ODO, TDO, TZ, NCU)
            if not court and druh.upper().replace(" ", "") in _NS_DRUHY:
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


def district_in_region(os_code: str, ks_code: str) -> bool:
    """True if district court `os_code` belongs to the region of regional/municipal court `ks_code`."""
    os_code, ks_code = os_code.upper(), ks_code.upper()
    if not os_code.startswith("OS") or len(ks_code) < 5:
        return False
    return os_code[2:5] == ks_code[2:5]


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
        """Get list of okresní soudy, optionally only those in the region of `ks_code`.

        The API ignores its `kod` filter and always returns all ~86 district courts,
        so the region is filtered here by the court code: KS<region><city> -> OS<region>…
        (e.g. KSZPCPM -> OSZPC*, MSPHAAB -> OSPHA*).
        """
        courts = self._get("/organizace/podrizene/lov", params={"kod": ks_code} if ks_code else None)
        if not ks_code:
            return courts
        return [c for c in courts if district_in_region(c.get("kod", ""), ks_code)]

    def get_case_subject(self, spis_zn: str | SpisZn,
                         court_code: str | None = None) -> str | None:
        """Fetch předmět řízení (case subject) from ZAHAJ_RIZ event detail.

        Returns the subject string, or None if not available.
        """
        try:
            detail = self.get_event_detail(spis_zn, court_code, "ZAHAJ_RIZ", 1)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code >= 500:
                raise
            return None
        for attr in detail.get("atributy", []):
            if attr.get("typ") == "PREDM_RIZ":
                value = attr.get("hodnota", "")
                if value and value != "-":
                    return value
        return None

    def get_hearing_details(self, spis_zn: str | SpisZn,
                            court_code: str | None = None,
                            case_data: dict | None = None) -> list[dict]:
        """Fetch hearing details from NAR_JED events.

        Uses /jednani/vyhledej as primary source, then supplements with
        NAR_JED events from the case timeline (including multi-day hearings
        listed in the ``jednani`` sub-array of each event).

        Returns list of dicts with datum, cas, druhJednani, jednaciSin, zruseno.
        """
        if isinstance(spis_zn, str):
            spis_zn = parse_spis_zn(spis_zn)
        code = court_code or spis_zn.court_code

        # Try the hearings endpoint first
        hearings_data = self.search_hearings(spis_zn, code)
        hearings = hearings_data.get("udalosti", [])

        # Only trust the endpoint if it has non-cancelled hearings;
        # otherwise fall through to the NAR_JED event detail fallback.
        has_active = any(
            h.get("jednaniZruseno") not in ("Ano", True)
            for h in hearings
        )
        if has_active:
            return hearings

        # Fall back: extract from NAR_JED events in case timeline
        if case_data is None:
            case_data = self.search_case(spis_zn, code)
        nar_events = [
            ev for ev in (case_data.get("udalosti") or [])
            if ev.get("udalost") == "NAR_JED" and not ev.get("zruseno")
        ]
        if not nar_events:
            return hearings  # return cancelled hearings if no NAR_JED at all

        results = []
        for ev in nar_events:
            # Collect all poradi values: the event itself + multi-day sub-items
            poradi_list = []
            main_poradi = ev.get("poradi")
            if main_poradi is not None:
                poradi_list.append(main_poradi)
            for sub in ev.get("jednani", []):
                sub_poradi = sub.get("poradiUdalosti")
                if sub_poradi is not None:
                    poradi_list.append(sub_poradi)

            if not poradi_list:
                logger.warning("NAR_JED event missing 'poradi', skipping: %s", ev)
                continue

            for poradi in poradi_list:
                try:
                    detail = self.get_event_detail(
                        spis_zn, code, "NAR_JED", poradi)
                except requests.HTTPError:
                    continue
                attrs = {a.get("typ"): a.get("hodnota", "")
                         for a in detail.get("atributy", [])
                         if a.get("typ")}
                zruseno = attrs.get("JED_ZRUS", "Ne") == "Ano"
                if zruseno:
                    continue
                # Parse "19.05.2026 08:30" → date + time
                d_zac = attrs.get("JED_D_ZAC", "")
                parts = d_zac.split(" ", 1)
                datum = parts[0] if parts[0] else ev.get("datum", "?")
                cas = parts[1] if len(parts) > 1 else "?"
                results.append({
                    "datum": datum,
                    "cas": cas,
                    "druhJednani": attrs.get("JED_DRUH", "?"),
                    "jednaciSin": attrs.get("JED_SIN", "?"),
                    "jednaniZruseno": False,
                })
        return results

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
    "ST_VEC_VYR": "Vyřízení věci",
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

# Event detail attribute labels
ATTR_LABELS = {
    "PREDM_RIZ": "Předmět řízení",
    "PRED_VEC": "Předaná věc",
    "JED_DRUH": "Druh jednání",
    "JED_SIN": "Jednací síň",
    "JED_D_ZAC": "Datum a čas jednání",
    "JED_ZRUS": "Jednání zrušeno",
}


def format_case_summary(data: dict, subject: str | None = None) -> str:
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
    if subject:
        lines.append(f"Předmět řízení: {subject}")

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


def format_hearings_summary(hearings: list[dict],
                            org: str = "?") -> str:
    """Format hearings data into human-readable summary."""
    lines = [f"Jednání — {org}"]

    if not hearings:
        lines.append("  Žádná jednání nařízena.")
        return "\n".join(lines)

    for ev in hearings:
        datum = ev.get("datum", "?")
        cas = ev.get("cas", "?")
        druh = ev.get("druhJednani", "?")
        sin = ev.get("jednaciSin", "?")
        zruseno = " [ZRUŠENO]" if ev.get("jednaniZruseno") else ""
        lines.append(f"  {datum} {cas}  {druh}{zruseno}")
        if ev.get("resitel"):
            lines.append(f"    Soudce: {ev['resitel']}")
        lines.append(f"    Síň: {sin}")

    return "\n".join(lines)
