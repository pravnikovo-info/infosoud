"""parse_query: plain-text značky, prefixes, číslo listu, years."""

import pytest

from infosoud import ParsedQuery, parse_query


def key(q: ParsedQuery):
    s = q.spis_zn
    return (s.cislo_senatu, s.druh_veci, s.bc_vec, s.rocnik)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("41 C 12/2024", (41, "C", 12, 2024)),
        ("41C12/2024", (41, "C", 12, 2024)),
        ("41 C 12 / 2024", (41, "C", 12, 2024)),
        ("3 P a Nc 53/2026", (3, "P a Nc", 53, 2026)),
        ("41 Cm 5/2024", (41, "Cm", 5, 2024)),
        ("1T64_2024", (1, "T", 64, 2024)),
        ("41 C 12/2024", (41, "C", 12, 2024)),
    ],
)
def test_basic_forms(text, expected, court_map):
    q = parse_query(text, court_map)
    assert key(q) == expected
    assert q.source == "text"
    assert q.court_code is None
    assert q.court_hint is None
    assert q.cislo_listu is None
    assert q.is_insolvency is False


@pytest.mark.parametrize(
    "text",
    [
        "sp. zn. 41 C 12/2024",
        "sp.zn. 41 C 12/2024",
        "Sp. zn.: 41 C 12/2024",
        "SP.ZN. 41 C 12/2024",
        "spisová značka 41 C 12/2024",
    ],
)
def test_spzn_prefixes(text, court_map):
    q = parse_query(text, court_map)
    assert key(q) == (41, "C", 12, 2024)
    assert q.court_hint is None


@pytest.mark.parametrize(
    "text", ["č. j. 41 C 12/2024-58", "čj. 41 C 12/2024-58", "Č.j. 41 C 12/2024-58", "č.j.: 41 C 12/2024-58"]
)
def test_cj_prefixes_and_cislo_listu(text, court_map):
    q = parse_query(text, court_map)
    assert key(q) == (41, "C", 12, 2024)
    assert q.cislo_listu == 58
    assert q.court_hint is None


@pytest.mark.parametrize(
    "text",
    ["41C 12/2024-58", "41 C 12/2024 - 58", "41 C 12/2024 – 58", "41 C 12/2024–58"],
)
def test_cislo_listu_variants(text, court_map):
    q = parse_query(text, court_map)
    assert key(q) == (41, "C", 12, 2024)
    assert q.cislo_listu == 58


@pytest.mark.parametrize(
    "yy, year", [("24", 2024), ("00", 2000), ("79", 2079), ("80", 1980), ("99", 1999)]
)
def test_two_digit_year(yy, year, court_map):
    assert parse_query(f"12 C 3/{yy}", court_map).spis_zn.rocnik == year


def test_insolvency_flag(court_map):
    q = parse_query("41 INS 1234/2024", court_map)
    assert q.is_insolvency is True
    assert q.spis_zn.druh_veci == "INS"


def test_ns_autodetect_kept(court_map):
    q = parse_query("8 Cdo 100/2024", court_map)
    assert q.court_code == "NS"
    assert q.spis_zn.court_code == "NS"
    assert q.court_hint is None


def test_explicit_court_beats_ns_autodetect(court_map):
    assert parse_query("8 Cdo 100/2024 KSJIMBM", court_map).court_code == "KSJIMBM"


def test_works_without_court_map():
    q = parse_query("41 C 12/2024 KSJIMBM")
    assert q.court_code == "KSJIMBM"


@pytest.mark.parametrize("text", ["", "   ", "hello", "Okresní soud Brno", "41 C 12", "41 C /2024"])
def test_no_spzn_raises_czech_error(text, court_map):
    with pytest.raises(ValueError, match="spisovou značku"):
        parse_query(text, court_map)


def test_non_string_raises():
    with pytest.raises(ValueError):
        parse_query(None)  # type: ignore[arg-type]


def test_result_is_frozen(court_map):
    q = parse_query("41 C 12/2024", court_map)
    with pytest.raises(Exception):
        q.court_code = "X"  # type: ignore[misc]


import pytest  # noqa: E402

from infosoud import explain_query, parse_query as _pq  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("1T682025", "1 T 68/2025"),
    ("1T682025 OSSCEDC", "1 T 68/2025"),
    ("1 T 68 2025", "1 T 68/2025"),
    ("41C12024", "41 C 1/2024"),
    ("1T202025", "1 T 20/2025"),
])
def test_without_slash(text, expected):
    assert _pq(text).spis_zn.canonical() == expected


def test_without_slash_keeps_court():
    assert _pq("1T682025 OSSCEDC", {"OSSCEDC": "Okresní soud Děčín"}).court_code == "OSSCEDC"


def test_implausible_year_without_slash_rejected():
    with pytest.raises(ValueError):
        _pq("1T683025")


def test_explain_partial():
    e = explain_query("1 T 68 OSSCEDC", {"OSSCEDC": "Okresní soud Děčín"})
    assert (e["senat"], e["druh"], e["cislo"], e["rocnik"], e["court_code"]) == ("1", "T", "68", None, "OSSCEDC")
    assert e["missing"] == ["ročník"]


def test_explain_empty():
    assert explain_query("")["missing"] == ["senát", "druh věci", "číslo", "ročník"]
