"""Front_desk permission regression (task 3006 / S2-IAM-022).

Acceptance mapping:
  A1: 9 allow + 14 deny parameterized, all pass
  A2: every deny -> 403, body error == permission_denied
  A3: site B -> all 9 allows become 403
  A4: front.visitor.read records -> exactly 6 site-A records
"""
import pytest

ALLOWED = [
    "front.visitor.read",
    "front.visitor.write",
    "front.checkin.write",
    "space.booking.read",
    "space.booking.write",
    "event.read",
    "crm.member.read_basic",
    "kb.article.read",
    "ai.assistant.use",
]

DENIED = [
    "crm.member.read",
    "crm.member.write",
    "crm.contact.read_sensitive",
    "crm.export",
    "opp.demand.read",
    "lead.prospect.read",
    "dash.site.read",
    "dash.exec.read",
    "iam.user.read",
    "iam.role.assign",
    "sys.config.manage",
    "audit.log.read",
]

# A2: deny probes must return 403 with error == permission_denied


@pytest.mark.parametrize("code", ALLOWED, ids=lambda c: f"allow:{c}")
def test_allowed_probe_200(client, code):
    r = client.get(f"/__probe__/{code}")
    assert r.status_code == 200, f"role=front_desk perm={code} expect=200 actual={r.status_code} body={r.text}"


@pytest.mark.parametrize("code", DENIED, ids=lambda c: f"deny:{c}")
def test_denied_probe_403(client, code):
    r = client.get(f"/__probe__/{code}")
    assert r.status_code == 403, f"role=front_desk perm={code} expect=403 actual={r.status_code} body={r.text}"
    assert r.json()["error"] == "permission_denied", (
        f"role=front_desk perm={code} expect=permission_denied actual={r.text}")


def test_matrix_deny_set_matches_task(client, role_matrix):
    denied = role_matrix["roles"]["front_desk"]["denied"]
    assert set(denied) == set(DENIED), "matrix seed must match task deny-list"


# A2 extra: real endpoints in deny-list


def test_real_iam_users_403(client):
    r = client.get("/api/iam/users")
    assert r.status_code == 403
    assert r.json()["error"] == "permission_denied"


def test_real_role_assign_403(client):
    r = client.post("/api/iam/users/user_x/roles", json={"role": "ops_manager"})
    assert r.status_code == 403
    assert r.json()["error"] == "permission_denied"


# A3: cross-site


@pytest.mark.parametrize("code", ALLOWED, ids=lambda c: f"siteB:{c}")
def test_site_b_allows_become_403(client_site_b, code):
    r = client_site_b.get(f"/__probe__/{code}", headers={"X-Site-Id": "site_B"})
    assert r.status_code == 403, f"cross-site perm={code} expect=403 actual={r.status_code} body={r.text}"


def test_cross_site_switch_then_back_no_leak(client_site_b):
    """Immutable ctx: after a 403 cross-site attempt, requests without header stay at site A."""
    r1 = client_site_b.get("/__probe__/front.visitor.read", headers={"X-Site-Id": "site_B"})
    assert r1.status_code == 403
    r2 = client_site_b.get("/__probe__/front.visitor.read/records")  # no header
    assert r2.status_code == 200
    ids = [i["id"] for i in r2.json()["items"]]
    assert set(ids) == {f"a_own_{i}" for i in range(3)} | {f"a_peer_{i}" for i in range(3)}, (
        "after rejected switch, default site A scope must not leak site B records")


# A4: data scope on records probe


def test_records_org_scope_spans_sites(client):
    """Pin org-scope semantics: kb.article.read (org) sees site A + site B."""
    r = client.get("/__probe__/kb.article.read/records")
    assert r.status_code == 200
    ids = {i["id"] for i in r.json()["items"]}
    assert len(ids) == 9, f"org scope must see 9 records across both sites, got {len(ids)}"
    assert {i for i in ids if i.startswith("b_")} == {f"b_{k}" for k in range(3)}


def test_records_site_scope(client):
    r = client.get("/__probe__/front.visitor.read/records")
    assert r.status_code == 200
    body = r.json()
    ids = [i["id"] for i in body["items"]]
    assert body["total"] == 6, f"expect 6 site-A records, got {body['total']}"
    assert all(not i.startswith("b_") for i in ids), "site B records must not leak"
    assert set(ids) == {f"a_own_{i}" for i in range(3)} | {f"a_peer_{i}" for i in range(3)}


def test_records_ai_self_scope(client):
    r = client.get("/__probe__/ai.assistant.use/records")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert set(ids) == {f"a_own_{i}" for i in range(3)}, "self scope: own records only"
