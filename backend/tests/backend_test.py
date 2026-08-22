"""Brand Memory OS — backend API regression suite (Hackathon change spec)."""
import os
import time

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE = base_url.rstrip("/") + "/api"

SAMPLE_HTML = (
    "<html><body><h1>Welcome to Alpine Kettle</h1><p>Meet your new morning ritual. "
    "Our hand-thrown kettle keeps water at the perfect pour temperature for filter coffee. "
    "Ships in 48 hours.</p><a href='#'>Shop the range</a></body></html>"
)


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def demo():
    r = requests.get(f"{BASE}/demo", timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["is_demo"] is True
    assert d["org_id"] and d["brand_id"]
    assert "northstar" not in d["org_id"].lower()
    return d


@pytest.fixture(scope="session")
def session_a():
    s = requests.Session()
    r = s.post(f"{BASE}/session", timeout=30)
    assert r.status_code == 200
    assert "bmos_owner" in s.cookies.get_dict()
    return s


@pytest.fixture(scope="session")
def session_b():
    s = requests.Session()
    assert s.post(f"{BASE}/session", timeout=30).status_code == 200
    return s


@pytest.fixture(scope="session")
def workspace_a(session_a):
    """Full onboarding: org -> brand -> guidelines -> data choice -> complete."""
    s = session_a
    org = s.post(f"{BASE}/organizations", json={
        "name": "TEST_Alpine Studio", "type": "brand", "role": "Lifecycle",
        "managed_brands": 2, "industry": "DTC"}, timeout=30)
    assert org.status_code == 200, org.text
    org = org.json()
    assert "owner_session_id" not in org
    assert org["onboarding_complete"] is False

    p = s.patch(f"{BASE}/organizations/{org['id']}/onboarding",
                json={"step": 2, "complete": False}, timeout=30)
    assert p.status_code == 200

    br = s.post(f"{BASE}/organizations/{org['id']}/brands", json={
        "name": "TEST_Alpine Kettle Co.", "url": "https://alpinekettle.test",
        "industry": "Housewares", "market": "US"}, timeout=30)
    assert br.status_code == 200, br.text
    brand = br.json()
    assert brand["org_id"] == org["id"]

    g = s.patch(f"{BASE}/brands/{brand['id']}/guidelines", json={
        "tone": ["warm"], "approved_claims": ["ships in 48 hours"],
        "prohibited_claims": ["detox"], "colors": [], "layout_rules": ["single CTA"],
        "cta_style": "verb-led"}, timeout=30)
    assert g.status_code == 200, g.text
    assert g.json()["version"] == 2

    fin = s.patch(f"{BASE}/organizations/{org['id']}/onboarding",
                  json={"step": 5, "complete": True, "data_choice": "upload"}, timeout=30)
    assert fin.status_code == 200
    return {"org_id": org["id"], "brand_id": brand["id"]}


# ---------------------------------------------------------------- session / onboarding
class TestSessionAndOnboarding:
    def test_session_returns_owned_orgs(self, session_a, workspace_a):
        r = session_a.post(f"{BASE}/session", timeout=30)
        assert r.status_code == 200
        ids = [o["id"] for o in r.json()["organizations"]]
        assert workspace_a["org_id"] in ids
        for o in r.json()["organizations"]:
            assert "owner_session_id" not in o

    def test_no_cookie_protected_route_401(self):
        r = requests.get(f"{BASE}/brands/whatever", timeout=30)
        assert r.status_code == 401

    def test_brand_persisted_with_guidelines(self, session_a, workspace_a):
        r = session_a.get(f"{BASE}/brands/{workspace_a['brand_id']}", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["brand"]["name"] == "TEST_Alpine Kettle Co."
        assert d["guidelines"]["prohibited_claims"] == ["detox"]
        assert d["organization"]["onboarding_complete"] is True
        assert "owner_session_id" not in d["organization"]

    def test_onboarding_step_validation(self, session_a, workspace_a):
        r = session_a.patch(f"{BASE}/organizations/{workspace_a['org_id']}/onboarding",
                            json={"step": 9}, timeout=30)
        assert r.status_code == 422

    def test_org_name_validation(self, session_a):
        r = session_a.post(f"{BASE}/organizations", json={"name": ""}, timeout=30)
        assert r.status_code == 422


# ---------------------------------------------------------------- tenant isolation
class TestIsolation:
    def test_other_session_cannot_read_brand(self, session_b, workspace_a):
        r = session_b.get(f"{BASE}/brands/{workspace_a['brand_id']}", timeout=30)
        assert r.status_code == 403

    def test_other_session_cannot_read_dashboard(self, session_b, workspace_a):
        r = session_b.get(f"{BASE}/brands/{workspace_a['brand_id']}/dashboard", timeout=30)
        assert r.status_code == 403

    def test_other_session_cannot_create_brand_in_org(self, session_b, workspace_a):
        r = session_b.post(f"{BASE}/organizations/{workspace_a['org_id']}/brands",
                           json={"name": "TEST_hijack"}, timeout=30)
        assert r.status_code == 403

    def test_other_session_cannot_list_campaigns(self, session_b, workspace_a):
        r = session_b.get(f"{BASE}/brands/{workspace_a['brand_id']}/campaigns", timeout=30)
        assert r.status_code == 403

    def test_demo_readable_by_any_session(self, session_b, demo):
        r = session_b.get(f"{BASE}/brands/{demo['brand_id']}", timeout=30)
        assert r.status_code == 200

    def test_unknown_brand_404(self, session_a):
        r = session_a.get(f"{BASE}/brands/deadbeefdeadbeef", timeout=30)
        assert r.status_code == 404


# ---------------------------------------------------------------- ingestion
class TestIngestion:
    def test_unsupported_file_type_rejected(self, session_a, workspace_a):
        r = session_a.post(f"{BASE}/brands/{workspace_a['brand_id']}/campaigns/upload",
                           files={"file": ("bad.txt", b"hello", "text/plain")},
                           data={"name": "TEST_bad"}, timeout=60)
        assert r.status_code == 400

    def test_upload_html_processes_to_ready(self, session_a, workspace_a):
        r = session_a.post(f"{BASE}/brands/{workspace_a['brand_id']}/campaigns/upload",
                           files={"file": ("sample-email.html", SAMPLE_HTML.encode(), "text/html")},
                           data={"name": "TEST_Alpine welcome"}, timeout=90)
        if r.status_code == 503:
            pytest.fail("Emergent Object Storage unavailable (503) — upload path blocked")
        assert r.status_code == 200, r.text
        cid = r.json()["campaign_id"]
        assert r.json()["status"] == "processing"

        status, camp = None, None
        for _ in range(30):
            time.sleep(4)
            g = session_a.get(f"{BASE}/campaigns/{cid}", timeout=30)
            assert g.status_code == 200
            camp = g.json()
            status = camp["status"]
            if status in ("ready", "failed"):
                break
        assert status == "ready", f"final status={status} err={(camp or {}).get('error')}"
        assert camp["extracted"], "no structured extraction"
        assert camp["extracted"].get("summary")
        assert camp["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2"
        assert "embedding" not in camp  # embeddings not leaked in API
        assert "_id" not in camp
        pytest.campaign_id = cid

    def test_campaign_appears_in_list_and_dashboard(self, session_a, workspace_a):
        lst = session_a.get(f"{BASE}/brands/{workspace_a['brand_id']}/campaigns", timeout=30)
        assert lst.status_code == 200
        names = [c["name"] for c in lst.json()]
        assert "TEST_Alpine welcome" in names
        d = session_a.get(f"{BASE}/brands/{workspace_a['brand_id']}/dashboard", timeout=30)
        assert d.status_code == 200
        rd = d.json()["readiness"]
        assert rd["analyzed"] >= 1
        assert rd["guidelines_set"] is True

    def test_outcome_recording_updates_campaign(self, session_a, workspace_a):
        cid = getattr(pytest, "campaign_id", None)
        if not cid:
            pytest.skip("no ready campaign from upload test")
        r = session_a.post(f"{BASE}/campaigns/{cid}/outcomes",
                           json={"open": 42, "click": 6.5, "conversion": 2.1}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["saved"] is True
        g = session_a.get(f"{BASE}/campaigns/{cid}", timeout=30).json()
        assert g["metrics"]["open"] == 42
        assert g["metrics"]["click"] == 6.5
        d = session_a.get(f"{BASE}/brands/{workspace_a['brand_id']}/dashboard", timeout=30).json()
        assert d["readiness"]["outcomes_attached"] >= 1

    def test_outcome_validation_rejects_out_of_range(self, session_a):
        cid = getattr(pytest, "campaign_id", None)
        if not cid:
            pytest.skip("no campaign")
        r = session_a.post(f"{BASE}/campaigns/{cid}/outcomes", json={"open": 900, "click": 1}, timeout=30)
        assert r.status_code == 422

    def test_campaign_file_retrievable(self, session_a):
        cid = getattr(pytest, "campaign_id", None)
        if not cid:
            pytest.skip("no campaign")
        r = session_a.get(f"{BASE}/campaigns/{cid}/file", timeout=60)
        assert r.status_code == 200
        assert b"Alpine Kettle" in r.content


# ---------------------------------------------------------------- retrieval / rules
def make_brief(sess, brand_id, objective, audience, offer, constraints=""):
    b = sess.post(f"{BASE}/brands/{brand_id}/briefs", json={
        "objective": objective, "audience": audience, "offer": offer,
        "constraints": constraints}, timeout=30)
    assert b.status_code == 200, b.text
    rec = sess.post(f"{BASE}/briefs/{b.json()['id']}/recommendations", timeout=180)
    assert rec.status_code == 200, rec.text
    return b.json(), rec.json()


class TestRetrievalAndRules:
    def test_brief_validation(self, session_a, demo):
        r = session_a.post(f"{BASE}/brands/{demo['brand_id']}/briefs",
                           json={"objective": "a", "audience": "b", "offer": "c"}, timeout=30)
        assert r.status_code == 422

    def test_matching_brief_returns_cited_evidence(self, session_a, demo):
        _, rec = make_brief(session_a, demo["brand_id"],
                            "Improve retention", "Active subscribers", "New seasonal roast")
        assert rec["source_campaign_ids"], "no evidence for a matching brief"
        assert rec["evidence_strength"] in ("strong", "moderate")
        for e in rec["evidence"]:
            assert 0 <= e["semantic_similarity"] <= 1
            assert e["semantic_similarity"] >= 0.35
            for k in ("objective_match", "audience_match", "evidence_quality", "score"):
                assert k in e
            assert "embedding" not in e["campaign"]
        assert rec["rule_violations"] == []
        assert rec["rationale"], "grounded rationale missing"
        assert rec["rationale_model"] == "gpt-5.4"
        assert "CAMPAIGN" in rec["rationale"].upper()
        pytest.good_rec_id = rec["id"]

    def test_no_evidence_brief_returns_empty(self, session_a, demo):
        _, rec = make_brief(session_a, demo["brand_id"],
                            "Astrophysics", "Mars explorers", "Moon rocks")
        assert rec["source_campaign_ids"] == [], f"fabricated evidence: {rec['source_campaign_ids']}"
        assert rec["evidence"] == []
        assert rec["evidence_strength"] == "insufficient"
        assert rec["rationale"] is None
        pytest.empty_rec_id = rec["id"]

    def test_prohibited_claim_blocks(self, session_a, demo):
        brief, rec = make_brief(session_a, demo["brand_id"],
                                "Improve retention", "Active subscribers", "detox blend")
        assert brief["brief_violations"], "brief pre-check missed prohibited claim"
        assert brief["status"] == "needs_edit"
        assert rec["rule_violations"], "recommendation not rule-blocked"
        v = rec["rule_violations"][0]
        assert v["severity"] == "blocked"
        assert v["rule"] == "detox"
        assert "detox" in v["remedy"]
        pytest.blocked_rec_id = rec["id"]

    def test_semantic_not_substring(self, session_a, demo):
        """Paraphrased brief with no shared words must still retrieve evidence."""
        _, rec = make_brief(session_a, demo["brand_id"],
                            "Keep existing members from lapsing",
                            "Loyal buyers", "Fresh single-origin beans")
        assert rec["source_campaign_ids"], "semantic retrieval failed on paraphrase"
        assert rec["evidence"][0]["semantic_similarity"] > 0.35


class TestBlueprint:
    """Self-contained: creates its own briefs so it works under xdist loadscope."""

    def test_export_valid(self, session_a, demo):
        _, rec = make_brief(session_a, demo["brand_id"],
                            "Improve retention", "Active subscribers", "New seasonal roast")
        assert rec["source_campaign_ids"]
        rid = rec["id"]
        r = session_a.post(f"{BASE}/recommendations/{rid}/blueprint", timeout=60)
        assert r.status_code == 200, r.text
        md = r.json()["markdown"]
        assert md.startswith("# Campaign blueprint")
        assert "## Guardrails applied" in md
        assert r.json()["grounded_in"]

    def test_export_blocked_by_rule_409(self, session_a, demo):
        _, rec = make_brief(session_a, demo["brand_id"],
                            "Improve retention", "Active subscribers", "detox blend")
        rid = rec["id"]
        r = session_a.post(f"{BASE}/recommendations/{rid}/blueprint", timeout=60)
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["violations"][0]["rule"] == "detox"
        assert detail["violations"][0]["remedy"]

    def test_export_no_evidence_422(self, session_a, demo):
        _, rec = make_brief(session_a, demo["brand_id"],
                            "Astrophysics", "Mars explorers", "Moon rocks")
        assert rec["source_campaign_ids"] == []
        r = session_a.post(f"{BASE}/recommendations/{rec['id']}/blueprint", timeout=60)
        assert r.status_code == 422

    def test_blueprint_isolation(self, session_b, workspace_a):
        b = session_b.get(f"{BASE}/brands/{workspace_a['brand_id']}/dashboard", timeout=30)
        assert b.status_code == 403
