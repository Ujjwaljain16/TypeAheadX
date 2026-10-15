"""Original API tests, now hermetic (seeded fixture data, real PostgreSQL + Redis) and with
assertions that can actually fail (the originals passed vacuously on an empty result list)."""
import pytest

pytestmark = pytest.mark.integration


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "typeaheadx-api"
    assert data["phase"] == "phase-5"


def test_valid_prefix(client):
    response = client.get("/suggest?q=iph")
    assert response.status_code == 200
    data = response.json()
    assert data["prefix"] == "iph"
    assert "total_results" in data
    assert isinstance(data["suggestions"], list)
    assert data["total_results"] == len(data["suggestions"]) == 5   # all iphone* seed rows, none vacuous

    # Check that all suggestions start with 'iph'
    for s in data["suggestions"]:
        assert s["query"].startswith("iph")

    # Check sorting
    counts = [s["historical_count"] for s in data["suggestions"]]
    assert counts == sorted(counts, reverse=True)
    assert data["suggestions"][0] == {"query": "iphone 15 pro case", "historical_count": 987}


def test_empty_prefix(client):
    response = client.get("/suggest?q=")
    assert response.status_code == 400


def test_no_results(client):
    response = client.get("/suggest?q=zzzzzz")
    assert response.status_code == 200
    data = response.json()
    assert data["prefix"] == "zzzzzz"
    assert data["total_results"] == 0
    assert data["suggestions"] == []


def test_case_insensitive(client):
    res1 = client.get("/suggest?q=iph")
    res2 = client.get("/suggest?q=IPH")

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json() == res2.json()
    assert res1.json()["suggestions"]
