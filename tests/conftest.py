import json
from pathlib import Path

import pytest

from inat_anki.normalise import ancestry_from_api, observation_from_api

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def observations():
    """Real (anonymised) observations, keyed by ID."""
    page = load_fixture("observations_page.json")
    return {d["id"]: observation_from_api(d) for d in page["results"]}


@pytest.fixture
def edge_cases():
    """Synthetic observations, keyed by ID (see scripts/make_fixtures.py)."""
    page = load_fixture("observations_edge_cases.json")
    return {d["id"]: observation_from_api(d) for d in page["results"]}


@pytest.fixture
def ancestries():
    return {t["id"]: ancestry_from_api(t) for t in load_fixture("taxa.json")["results"]}
