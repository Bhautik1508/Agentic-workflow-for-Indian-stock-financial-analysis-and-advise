import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_search_valid_stock():
    response = client.get("/api/search/tata")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    # Tata Motors or Tata Steel should be in results
    assert len(data["results"]) > 0
    # Every result should have a name and ticker
    for r in data["results"]:
        assert "name" in r
        assert "ticker" in r

def test_search_invalid_stock():
    response = client.get("/api/search/abcdefghijklmnop")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    # Random invalid string should yield empty results
    assert len(data["results"]) == 0

if __name__ == "__main__":
    pytest.main(["-v", "test_search.py"])
