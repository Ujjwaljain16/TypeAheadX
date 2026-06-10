import pytest
from fastapi.testclient import TestClient


from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "typeaheadx-api"
    assert data["phase"] == "phase-5"

def test_valid_prefix():
    response = client.get("/suggest?q=iph")
    assert response.status_code == 200
    data = response.json()
    assert data["prefix"] == "iph"
    assert "total_results" in data
    assert isinstance(data["suggestions"], list)
    
    # Check that all suggestions start with 'iph'
    for s in data["suggestions"]:
        assert s["query"].startswith("iph")
        
    # Check sorting
    counts = [s["historical_count"] for s in data["suggestions"]]
    assert counts == sorted(counts, reverse=True)

def test_empty_prefix():
    response = client.get("/suggest?q=")
    assert response.status_code == 400

def test_no_results():
    response = client.get("/suggest?q=zzzzzz")
    assert response.status_code == 200
    data = response.json()
    assert data["prefix"] == "zzzzzz"
    assert data["total_results"] == 0
    assert data["suggestions"] == []

def test_case_insensitive():
    res1 = client.get("/suggest?q=iph")
    res2 = client.get("/suggest?q=IPH")
    
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json() == res2.json()
