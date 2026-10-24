"""parse_query / resolve_court: court names, locatives, codes, ISIR abbreviations."""

import pytest

from infosoud import parse_query, resolve_court


@pytest.mark.parametrize(
    "text, code, hint",
    [
        ("4 T 21/2025 melnik", "OSSTCME", "melnik"),
        ("4 T 21/2025 OS Mělník", "OSSTCME", "OS Mělník"),
        ("41 C 12/2024 Okresní soud Brno-venkov", "OSJIMBV", "Okresní soud Brno-venkov"),
        ("Okresní soud Brno-venkov 41 C 12/2024", "OSJIMBV", "Okresní soud Brno-venkov"),
        ("OS Mělník, 4 T 21/2025", "OSSTCME", "OS Mělník"),
        ("KS Brno 41 Cm 5/2024", "KSJIMBM", "KS Brno"),
        ("41 Cm 5/2024 KSJIMBM", "KSJIMBM", "KSJIMBM"),
        ("OSSTCME 4 T 21/2025", "OSSTCME", "OSSTCME"),
        ("sp. zn. 4 T 21/2025 OSSTCME", "OSSTCME", "OSSTCME"),
    ],
)
def test_court_before_or_after(text, code, hint, court_map):
    q = parse_query(text, court_map)
    assert q.court_code == code
    assert q.court_hint == hint
    assert q.spis_zn.court_code == code


@pytest.mark.parametrize(
    "name, code",
    [
        ("Krajský soud v Brně", "KSJIMBM"),
        ("Okresní soud v Mělníku", "OSSTCME"),
        ("Městský soud v Praze", "MSPHAAB"),
        ("Obvodní soud pro Prahu 2", "OSPHA02"),
        ("Obvodní soud pro Prahu 1", "OSPHA01"),
        ("Obvodní soud pro Prahu 10", "OSPHA10"),
        ("Okresní soud v Českých Budějovicích", "OSJICCB"),
        ("Krajský soud v Plzni", "KSZPCPM"),
        ("Okresní soud v Plzni-město", "OSZPCPM"),
        ("Krajský soud v Hradci Králové", "KSVYCHK"),
        ("Krajský soud v Ostravě", "KSSEMOS"),
        ("Krajský soud v Ústí nad Labem", "KSSCEUL"),
        ("Vrchní soud v Olomouci", "VSSEMOL"),
        ("Okresní soud v Děčíně", "OSSCEDC"),
        ("Okresní soud v Kutné Hoře", "OSSTCKH"),
        ("Nejvyšší soud", "NS"),
        ("NS ČR", "NS"),
        ("MELNIK", "OSSTCME"),
        ("  okresni   soud  v  melniku ", "OSSTCME"),
        ("Městský soud v Brně", "OSJIMBM"),
    ],
)
def test_resolve_court_names_and_locatives(name, code, court_map):
    assert resolve_court(name, court_map) == code


def test_prague_district_numbers_are_exact(court_map):
    assert resolve_court("Praha 1", court_map) == "OSPHA01"
    assert resolve_court("Praha 10", court_map) == "OSPHA10"


def test_unknown_name_returns_none(court_map):
    assert resolve_court("Okresní soud v Atlantidě", court_map) is None
    assert resolve_court("", court_map) is None
    assert resolve_court("Okresní soud", court_map) is None


def test_ambiguous_exact_tie_returns_none(court_map):
    extra = {**court_map, "OSXXXAA": "Okresní soud Foo", "OSXXXBB": "Obvodní soud Foo"}
    assert resolve_court("Foo", extra) is None


def test_code_token_valid(court_map):
    assert resolve_court("OSSTCME", court_map) == "OSSTCME"
    assert resolve_court("osstcme", court_map) == "OSSTCME"


def test_invalid_code_not_accepted_with_court_map(court_map):
    q = parse_query("OSBRV 4 T 21/2025", court_map)
    assert q.court_code is None
    assert q.court_hint == "OSBRV"
    assert resolve_court("OSBRV", court_map) is None


@pytest.mark.parametrize(
    "abbr, code",
    [
        ("KSPH", "KSSTCAB"), ("MSPH", "MSPHAAB"), ("KSBR", "KSJIMBM"),
        ("KSOS", "KSSEMOS"), ("KSOL", "KSSEMOC"), ("KSPA", "KSVYCPA"),
        ("KSLB", "KSSCELB"), ("KSUL", "KSSCEUL"), ("KSCB", "KSJICCB"),
        ("KSHK", "KSVYCHK"), ("KSPL", "KSZPCPM"),
    ],
)
def test_isir_abbreviations(abbr, code, court_map):
    assert resolve_court(abbr, court_map) == code
    assert code in court_map


def test_isir_insolvency_line(court_map):
    q = parse_query("KSBR 41 INS 1234/2024", court_map)
    assert q.is_insolvency is True
    assert q.court_code == "KSJIMBM"
    assert q.court_hint == "KSBR"
    assert q.spis_zn.canonical() == "41 INS 1234/2024"


def test_historical_court_resolvable(court_map):
    assert resolve_court("OSJIMLH", court_map) == "OSJIMLH"


def test_falls_back_to_builtin_codes_without_map():
    assert resolve_court("Krajský soud v Brně", {}) == "KSJIMBM"


def test_same_name_duplicate_codes_prefer_builtin(court_map):
    assert resolve_court("Vrchní soud v Praze", court_map) == "VSPHAAB"
