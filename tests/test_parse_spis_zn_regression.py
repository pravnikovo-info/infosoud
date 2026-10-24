"""Regression tests: parse_spis_zn behaviour must not change."""

import pytest

from infosoud import parse_spis_zn
from infosoud.client import SpisZn


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1 T 64/2024", SpisZn(1, "T", 64, 2024)),
        ("1T64/2024", SpisZn(1, "T", 64, 2024)),
        ("1T 64/2024", SpisZn(1, "T", 64, 2024)),
        ("1 T64/2024", SpisZn(1, "T", 64, 2024)),
        ("1T64_2024", SpisZn(1, "T", 64, 2024)),
        ("1 T 64 / 2024", SpisZn(1, "T", 64, 2024)),
        ("43T191_2024", SpisZn(43, "T", 191, 2024)),
        ("43 T 191/2024 OSPHA09", SpisZn(43, "T", 191, 2024, "OSPHA09")),
        ("2 To 29/2023", SpisZn(2, "To", 29, 2023)),
        ("6To436/2025", SpisZn(6, "To", 436, 2025)),
        ("3 P A NC 53/2026", SpisZn(3, "P A NC", 53, 2026)),
        ("3 P A NC 53/2026 OSSTCKH", SpisZn(3, "P A NC", 53, 2026, "OSSTCKH")),
        ("3P.A.NC53_2026", SpisZn(3, "P A NC", 53, 2026)),
        ("  1 T 64/2024  ", SpisZn(1, "T", 64, 2024)),
        ("8 Cdo 100/2024", SpisZn(8, "Cdo", 100, 2024, "NS")),
        ("7 Tdo 5/2023", SpisZn(7, "Tdo", 5, 2023, "NS")),
    ],
)
def test_accepted_inputs(text, expected):
    assert parse_spis_zn(text) == expected


@pytest.mark.parametrize("text", ["", "hello", "1 T 64", "T 64/2024", "1 T 64/24"])
def test_rejected_inputs(text):
    with pytest.raises(ValueError):
        parse_spis_zn(text)


def test_district_in_region():
    from infosoud.client import district_in_region
    assert district_in_region("OSZPCTC", "KSZPCPM")
    assert not district_in_region("OSPHA02", "KSZPCPM")
    assert district_in_region("OSPHA02", "MSPHAAB")
    assert not district_in_region("KSJIMBM", "KSJIMBM")


def test_get_district_courts_filters_region():
    from infosoud.client import InfoSoudClient
    c = InfoSoudClient(delay=0)
    c._get = lambda path, params=None: [{"kod": "OSZPCTC"}, {"kod": "OSPHA02"}, {"kod": "OSZPCRO"}]
    assert [x["kod"] for x in c.get_district_courts("KSZPCPM")] == ["OSZPCTC", "OSZPCRO"]
    assert len(c.get_district_courts()) == 3
