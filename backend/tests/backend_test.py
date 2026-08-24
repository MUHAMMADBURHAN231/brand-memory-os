"""Opt-in deployed API smoke tests. Set TEST_API_URL to run."""
import os
import uuid

import pytest
import requests

ROOT = os.environ.get("TEST_API_URL")
pytestmark = pytest.mark.skipif(not ROOT, reason="TEST_API_URL not configured")
BASE = f"{(ROOT or '').rstrip('/')}/api"


def account() -> requests.Session:
    session = requests.Session()
    marker = uuid.uuid4().hex[:10]
    response = session.post(f"{BASE}/auth/register", json={
        "name": "Security Test", "email": f"security-{marker}@example.com",
        "password": f"correct-horse-{marker}",
    }, timeout=30)
    assert response.status_code == 201, response.text
    session.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return session


def test_auth_csrf_and_tenant_isolation():
    owner, stranger = account(), account()
    org = owner.post(f"{BASE}/organizations", json={"name": "Test Org", "type": "brand"}, timeout=30)
    assert org.status_code == 200
    brand = owner.post(f"{BASE}/organizations/{org.json()['id']}/brands", json={"name": "Test Brand"}, timeout=30)
    assert brand.status_code == 200
    assert owner.get(f"{BASE}/brands/{brand.json()['id']}", timeout=30).status_code == 200
    assert stranger.get(f"{BASE}/brands/{brand.json()['id']}", timeout=30).status_code == 403


def test_demo_is_explicitly_read_only():
    demo = requests.get(f"{BASE}/demo", timeout=30).json()
    headers = {"X-Demo-Access": "read-only"}
    assert requests.get(f"{BASE}/brands/{demo['brand_id']}/dashboard", headers=headers, timeout=30).status_code == 200
    assert requests.patch(
        f"{BASE}/brands/{demo['brand_id']}/guidelines", headers=headers,
        json={"tone": [], "approved_claims": [], "prohibited_claims": [], "colors": [], "layout_rules": [], "cta_style": ""}, timeout=30,
    ).status_code in {401, 403}
