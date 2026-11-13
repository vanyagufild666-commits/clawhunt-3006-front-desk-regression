"""Fixtures: fictional org, sites A/B, front_desk employee, probe_records.

Data (all fictional):
  org  : org_test (1)
  sites: site_A (home), site_B
  user : 前台测试员（虚构） - front_desk at site A only
  probe_records: site A own 3, site A colleague 3, site B 3
"""
import copy
import os

os.environ.setdefault("APP_ENV", "test")  # probe routes mount only in test env

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.permissions import PROBE_RECORDS
from app.tenant import TenantContext

import yaml

ORG_ID = "org_test"
SITE_A = "site_A"
SITE_B = "site_B"
USER_ID = "user_fd_001"


@pytest.fixture(scope="session")
def role_matrix():
    with open("role_matrix.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _records():
    recs = []
    for i in range(3):
        recs.append({"id": f"a_own_{i}", "org_id": ORG_ID, "site_id": SITE_A,
                     "owner_id": USER_ID, "title": f"前台本人记录 {i}（虚构）"})
    for i in range(3):
        recs.append({"id": f"a_peer_{i}", "org_id": ORG_ID, "site_id": SITE_A,
                     "owner_id": "user_peer_002", "title": f"同事记录 {i}（虚构）"})
    for i in range(3):
        recs.append({"id": f"b_{i}", "org_id": ORG_ID, "site_id": SITE_B,
                     "owner_id": "user_b_003", "title": f"会所B记录 {i}（虚构）"})
    return recs


@pytest.fixture()
def client(role_matrix):
    PROBE_RECORDS.clear()
    PROBE_RECORDS.extend(_records())
    app = create_app()
    app.state.auth_state = TenantContext(
        org_id=ORG_ID, user_id=USER_ID, site_id=SITE_A, role="front_desk",
        role_matrix=role_matrix, home_site_id=SITE_A,
    )
    app.state.auth_state.role_matrix.setdefault("_user_sites", {})[USER_ID] = [SITE_A]
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client_site_b(role_matrix):
    """Employee at home site A; requests carry X-Site-Id: site_B.

    Employee membership is only [site_A], so every permission check must 403.
    The switch branch (not a pre-mutated context) is what gets exercised.
    """
    PROBE_RECORDS.clear()
    PROBE_RECORDS.extend(_records())
    app = create_app()
    app.state.auth_state = TenantContext(
        org_id=ORG_ID, user_id=USER_ID, site_id=SITE_A, role="front_desk",
        role_matrix={"roles": copy.deepcopy(role_matrix["roles"]),
                     "_user_sites": {USER_ID: [SITE_A]}},
        home_site_id=SITE_A,
    )
    with TestClient(app) as c:
        yield c
