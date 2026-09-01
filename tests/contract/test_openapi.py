from fastapi.testclient import TestClient
from noemosyne_api.main import app


def test_versioned_openapi_and_health_contract() -> None:
    client = TestClient(app)
    response = client.get("/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    schema = client.get("/v1/openapi.json").json()
    assert schema["info"]["title"] == "Noemosyne API"
    required = {
        "/v1/claims/{claim_id}/context",
        "/v1/claims/{claim_id}/history",
        "/v1/claims:search",
        "/v1/graph:trace",
        "/v1/proposals/{proposal_id}:apply",
    }
    assert required <= schema["paths"].keys()
