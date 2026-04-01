"""CLI for InfoSoud — Czech court case lookup.

Usage:
    python -m infosoud "1 T 64/2024" OSSCEDC
    python -m infosoud "1T64_2024 OSSCEDC"
    python -m infosoud "4 T 21/2025 melnik"
    python -m infosoud --hearings "1 T 64/2024" OSSCEDC
    python -m infosoud --courts
    python -m infosoud --json "1 T 64/2024" OSSCEDC
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import InfoSoudClient, parse_spis_zn, EVENT_LABELS


def format_case_summary(data: dict) -> str:
    """Format case data into human-readable summary."""
    lines = []
    org = data.get("organizace", "?")
    nadr = data.get("nadrizenaOrganizace", "")
    stav = data.get("stav") or "?"
    stav_datum = data.get("stavDatum", "")

    spzn = (f"{data.get('cislo', '') or ''} {data.get('druh', '') or ''} "
            f"{data.get('bcVec', '') or ''}/{data.get('rocnik', '') or ''}")
    lines.append(f"Sp. zn.: {spzn}")
    lines.append(f"Soud: {org}" + (f" ({nadr})" if nadr else ""))
    lines.append(f"Stav: {stav}" + (f" (od {stav_datum})" if stav_datum else ""))

    events = data.get("udalosti") or []
    if events:
        lines.append(f"\nUdálosti ({len(events)}):")
        for ev in events:
            code = ev.get("udalost", "?")
            label = EVENT_LABELS.get(code, code)
            datum = ev.get("datum", "?")
            zruseno = " [ZRUŠENO]" if ev.get("zruseno") else ""
            lines.append(f"  {datum}  {label}{zruseno}")

    return "\n".join(lines)


def format_hearings_summary(data: dict) -> str:
    """Format hearings data into human-readable summary."""
    lines = [f"Jednání — {data.get('organizace', '?')}"]
    events = data.get("udalosti") or []
    if not events:
        lines.append("  Žádná jednání nařízena.")
        return "\n".join(lines)
    for ev in events:
        zruseno = " [ZRUŠENO]" if ev.get("jednaniZruseno") else ""
        lines.append(f"  {ev.get('datum', '?')} {ev.get('cas', '?')}  "
                     f"{ev.get('druhJednani', '?')}{zruseno}")
        lines.append(f"    Soudce: {ev.get('resitel', '?')}")
        lines.append(f"    Síň: {ev.get('jednaciSin', '?')}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        prog="infosoud",
        description="InfoSoud — vyhledávání v soudních řízeních (infosoud.gov.cz)",
    )
    parser.add_argument("spis_zn", nargs="?",
                        help="Spisová značka (např. '1 T 64/2024', '1T64_2024 OSSCEDC', '4 T 21/2025 melnik')")
    parser.add_argument("court_code", nargs="?",
                        help="Kód soudu (nepovinné pokud je v sp. zn.)")
    parser.add_argument("--hearings", action="store_true",
                        help="Zobrazit nařízená jednání")
    parser.add_argument("--courts", action="store_true",
                        help="Vypsat seznam soudů")
    parser.add_argument("--json", dest="json_out", action="store_true",
                        help="Výstup v JSON")
    parser.add_argument("--csv", dest="csv_out", action="store_true",
                        help="Výstup v CSV")

    args = parser.parse_args()
    client = InfoSoudClient()

    if args.courts:
        courts = client.build_court_map()
        if args.json_out:
            print(json.dumps(courts, ensure_ascii=False, indent=2))
        elif args.csv_out:
            print("kod,nazev")
            for code, name in sorted(courts.items(), key=lambda x: x[1]):
                print(f"{code},{name}")
        else:
            for code, name in sorted(courts.items(), key=lambda x: x[1]):
                print(f"  {code}  {name}")
            print(f"\nCelkem: {len(courts)} soudů")
        return

    if not args.spis_zn:
        parser.print_help()
        sys.exit(1)

    # Try to resolve court name from input
    spis_zn_raw = args.spis_zn
    court_code = args.court_code or ""

    if not court_code:
        # Check if trailing text in spis_zn is a court name
        import re
        m = re.match(
            r"((?:\d+\s*[A-Za-z]+\s*\d+\s*[/_]\s*\d{4}))\s+(.+)$",
            spis_zn_raw.strip(),
        )
        if m:
            spzn_part = m.group(1).strip()
            tail = m.group(2).strip()
            if re.match(r"^[A-Z][A-Z0-9]{4,9}$", tail):
                spis_zn_raw, court_code = spzn_part, tail
            else:
                resolved = client.resolve_court_name(tail)
                if resolved:
                    spis_zn_raw, court_code = spzn_part, resolved

    spis_zn = parse_spis_zn(spis_zn_raw)
    code = court_code or spis_zn.court_code

    if not code:
        print("Chybí kód soudu. Zadejte jako druhý argument nebo součást sp. zn.",
              file=sys.stderr)
        print("Příklad: python -m infosoud '1 T 64/2024' OSSCEDC", file=sys.stderr)
        print("         python -m infosoud '4 T 21/2025 melnik'", file=sys.stderr)
        sys.exit(1)

    try:
        if args.hearings:
            data = client.search_hearings(spis_zn, code)
            if args.json_out:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print(format_hearings_summary(data))
        else:
            data = client.search_case(spis_zn, code)
            if args.json_out:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            elif args.csv_out:
                events = data.get("udalosti") or []
                print("datum;udalost;zruseno;souvisejici_spzn;soud")
                for ev in events:
                    code_ev = ev.get("udalost", "")
                    label = EVENT_LABELS.get(code_ev, code_ev)
                    zr = "Ano" if ev.get("zruseno") else ""
                    zid = ev.get("znackaId", {})
                    rel = (f"{zid.get('cisloSenatu', '')} {zid.get('druhVeci', '')} "
                           f"{zid.get('bcVec', '')}/{zid.get('rocnik', '')} "
                           f"{zid.get('organizace', '')}").strip()
                    print(f"{ev.get('datum', '')};{label};{zr};{rel};{data.get('organizace', '')}")
            else:
                print(format_case_summary(data))
    except Exception as e:
        print(f"Chyba: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
