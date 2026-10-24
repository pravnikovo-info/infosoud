"""parse_query: URL inputs (new/legacy InfoSoud, ISIR, own site)."""

import pytest

from infosoud import parse_query

NEW = "https://infosoud.gov.cz/detail-rizeni?"
LEGACY = "https://infosoud.justice.cz/InfoSoud/public/search.do?"


def test_new_infosoud_district_court(court_map):
    q = parse_query(
        NEW + "typOrganizace=VSECHNY_KRAJE&druhOrganizace=KSSTCAB&okresniSoud=OSSTCME"
        "&cisloSenatu=4&druhVeci=T&bcVec=21&rocnik=2025", court_map)
    assert q.source == "infosoud_url"
    assert q.court_code == "OSSTCME"
    assert q.spis_zn.canonical() == "4 T 21/2025"
    assert q.is_insolvency is False


def test_new_infosoud_regional_court_without_okresni(court_map):
    q = parse_query(
        NEW + "typOrganizace=VSECHNY_KRAJE&druhOrganizace=KSJIMBM&cisloSenatu=41&druhVeci=Cm&bcVec=5&rocnik=2024",
        court_map)
    assert q.court_code == "KSJIMBM"
    assert q.spis_zn.canonical() == "41 Cm 5/2024"


def test_new_infosoud_nejvyssi(court_map):
    q = parse_query(NEW + "typOrganizace=NEJVYSSI&cisloSenatu=8&druhVeci=Cdo&bcVec=100&rocnik=2024", court_map)
    assert q.court_code == "NS"


def test_new_infosoud_unknown_court_kept_as_hint(court_map):
    q = parse_query(NEW + "okresniSoud=OSBRV&cisloSenatu=4&druhVeci=T&bcVec=21&rocnik=2025", court_map)
    assert q.court_code is None
    assert q.court_hint == "OSBRV"


def test_new_infosoud_multiword_druh_and_urlencoding(court_map):
    q = parse_query(NEW + "okresniSoud=OSSTCKH&cisloSenatu=3&druhVeci=P+a+Nc&bcVec=53&rocnik=2026", court_map)
    assert q.spis_zn.canonical() == "3 P a Nc 53/2026"


def test_legacy_url_district(court_map):
    q = parse_query(
        LEGACY + "org=OSSTCME&krajOrg=KSSTCAB&cisloSenatu=4&druhVec=T&bcVec=21&rocnik=2025"
        "&typSoudu=os&rowsAtOnce=50&druhVec=T", court_map)
    assert q.source == "infosoud_legacy_url"
    assert q.court_code == "OSSTCME"
    assert q.spis_zn.canonical() == "4 T 21/2025"


def test_legacy_url_regional(court_map):
    q = parse_query(
        LEGACY + "org=KSJIMBM&krajOrg=KSJIMBM&cisloSenatu=41&druhVec=Cm&bcVec=5&rocnik=2024&typSoudu=ks",
        court_map)
    assert q.court_code == "KSJIMBM"


def test_legacy_url_nejvyssi(court_map):
    q = parse_query(LEGACY + "org=NSJIMBM&krajOrg=NSJIMBM&cisloSenatu=8&druhVec=Cdo&bcVec=1&rocnik=2024", court_map)
    assert q.court_code == "NS"


def test_legacy_url_insolvency_flag(court_map):
    q = parse_query(LEGACY + "krajOrg=KSJIMBM&cisloSenatu=41&druhVec=INS&bcVec=1234&rocnik=2024", court_map)
    assert q.is_insolvency is True


ISIR = "https://isir.justice.cz/isir/ueu/"


def test_isir_spis_znacka_param(court_map):
    q = parse_query(ISIR + "evidence_upadcu_detail.do?id=abc&spis_znacka=KSBR+41+INS+1234%2F2024", court_map)
    assert q.source == "isir_url"
    assert q.is_insolvency is True
    assert q.court_code == "KSJIMBM"
    assert q.spis_zn.canonical() == "41 INS 1234/2024"


def test_isir_separate_params(court_map):
    q = parse_query(
        ISIR + "vysledek_lustrace.do?bc_vec=1234&rocnik=2024&cislo_senatu=41&druh_vec=INS&id_osoby_puvodce=KSBR",
        court_map)
    assert q.source == "isir_url"
    assert q.court_code == "KSJIMBM"
    assert q.spis_zn.canonical() == "41 INS 1234/2024"


def test_isir_without_senate_uses_zero(court_map):
    q = parse_query(ISIR + "evidence_upadcu_detail.do?druhVec=INS&bcVec=1234&rocnik=2024", court_map)
    assert q.is_insolvency is True
    assert q.spis_zn.cislo_senatu == 0
    assert q.court_code is None


def test_own_url(court_map):
    q = parse_query("https://infosoud.pravnikovo.info/case?sp_zn=1T64_2024&court_code=OSSCEDC", court_map)
    assert q.source == "own_url"
    assert q.court_code == "OSSCEDC"
    assert q.spis_zn.canonical() == "1 T 64/2024"


def test_own_url_without_court(court_map):
    q = parse_query("https://infosoud.pravnikovo.info/case?sp_zn=8Cdo100_2024", court_map)
    assert q.court_code == "NS"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        NEW + "cisloSenatu=4&druhVeci=T",
        "https://infosoud.pravnikovo.info/case",
        "https://infosoud.pravnikovo.info/case?sp_zn=nonsense",
    ],
)
def test_unusable_urls_raise(url, court_map):
    with pytest.raises(ValueError, match="spisovou značku|odkaz"):
        parse_query(url, court_map)
