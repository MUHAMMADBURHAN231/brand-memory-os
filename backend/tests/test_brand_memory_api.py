"""Regression coverage for Brand Memory workspace, ranking, rules, export, and outcomes."""
import os
import requests
import pytest

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


@pytest.fixture(scope="module")
def api():
    return requests.Session()


def test_workspace_and_seeded_campaigns(api):
    workspace = api.get(f"{BASE_URL}/api/workspace")
    campaigns = api.get(f"{BASE_URL}/api/campaigns")
    assert workspace.status_code == 200
    assert workspace.json()["name"] == "Northstar Coffee Co."
    assert campaigns.status_code == 200
    data = campaigns.json()
    assert len(data) >= 3
    assert {c["id"] for c in data} >= {"cmp-104", "cmp-087", "cmp-062"}
    assert all("_id" not in c for c in data)


def test_recommendations_are_ranked_and_include_evidence(api):
    response = api.post(f"{BASE_URL}/api/recommendations", json={
        "objective": "Improve retention", "audience": "Active subscribers",
        "offer": "New seasonal roast", "constraints": ""
    })
    assert response.status_code == 200
    data = response.json()
    assert data["rules_checked"] is True
    assert data["evidence_count"] >= 2
    recs = data["recommendations"]
    assert recs[0]["id"] == "cmp-104"
    assert all(r["score"] >= 0 and r["evidence"] for r in recs)
    assert any(r["status"] == "limited" for r in recs)


def test_no_evidence_brief_is_honest(api):
    response = api.post(f"{BASE_URL}/api/recommendations", json={
        "objective": "Astrology", "audience": "Mars explorers", "offer": "Moon rocks", "constraints": ""
    })
    assert response.status_code == 200
    data = response.json()
    assert data["evidence_count"] == 0
    assert all(r["matched_attributes"] == [] for r in data["recommendations"])
    assert all("closest available" in r["why"] for r in data["recommendations"])


def test_blueprint_hard_rule_blocks_and_valid_export(api):
    brief = {"objective": "Retention", "audience": "Subscribers", "offer": "New roast", "constraints": ""}
    blocked = api.post(f"{BASE_URL}/api/blueprint?recommendation_id=cmp-104", json={**brief, "offer": "Guaranteed energy"})
    assert blocked.status_code == 409
    assert "blocked by brand rule" in blocked.json()["detail"]
    exported = api.post(f"{BASE_URL}/api/blueprint?recommendation_id=cmp-104", json=brief)
    assert exported.status_code == 200
    assert "markdown" in exported.json()
    assert "The Monday, roasted better" not in exported.json()["markdown"]


def test_rules_update_and_outcome_persists(api):
    rules = api.get(f"{BASE_URL}/api/rules").json()
    rules["tone"] = rules["tone"] + ["TEST_precise"]
    saved = api.put(f"{BASE_URL}/api/rules", json=rules)
    assert saved.status_code == 200
    assert "TEST_precise" in api.get(f"{BASE_URL}/api/rules").json()["tone"]
    outcome = api.post(f"{BASE_URL}/api/outcomes", json={"campaign_id": "cmp-062", "open_rate": 51.4, "click_rate": 8.6, "conversion_rate": 4.4})
    assert outcome.status_code == 200
    updated = {c["id"]: c for c in api.get(f"{BASE_URL}/api/campaigns").json()}["cmp-062"]
    assert updated["outcome"]["status"] == "complete"
    assert updated["outcome"]["click_rate"] == 8.6