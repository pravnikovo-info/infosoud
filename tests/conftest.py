"""Shared fixtures: a small offline court map (the live API is never called)."""

import pytest

from infosoud.client import EXTRA_COURTS, HISTORICAL_COURTS, KS_CODES

_DISTRICT_COURTS = {
    "OSSTCME": "Okresní soud v Mělníku",
    "OSSTCKH": "Okresní soud v Kutné Hoře",
    "OSJIMBV": "Okresní soud Brno-venkov",
    "OSJIMBM": "Městský soud v Brně",
    "OSPHA01": "Obvodní soud pro Prahu 1",
    "OSPHA02": "Obvodní soud pro Prahu 2",
    "OSPHA10": "Obvodní soud pro Prahu 10",
    "OSSCEDC": "Okresní soud v Děčíně",
    "OSJICCB": "Okresní soud v Českých Budějovicích",
    "OSZPCPM": "Okresní soud Plzeň-město",
}


@pytest.fixture(scope="session")
def court_map():
    return {**KS_CODES, **EXTRA_COURTS, **HISTORICAL_COURTS, **_DISTRICT_COURTS}
