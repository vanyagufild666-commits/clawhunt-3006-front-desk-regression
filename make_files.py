"""3006: front_desk role permission regression tests.

Deliverable structure:
  role_matrix.yml          - seed matrix (allowed/denied for front_desk)
  app/__init__.py
  app/permissions.py       - require_permission dependency + probe routes (test-only)
  app/main.py              - FastAPI app factory with fixtures wiring
  tests/conftest.py        - fixtures: org, sites A/B, employee, probe_records
  tests/test_front_desk.py - parameterized regression (9 allow + 14 deny + cross-site + scope)
  README.md                - run instructions + matrix rationale
"""

# ---------- role_matrix.yml ----------
ROLE_MATRIX = """\
# role_matrix.yml - seed of built-in role permission matrix (fictional platform)
# scope levels: site | org | self
roles:
  front_desk:
    title: 前台接待
    level: site
    allowed:
      front.visitor.read: site
      front.visitor.write: site
      front.checkin.write: site
      space.booking.read: site
      space.booking.write: site
      event.read: site
      crm.member.read_basic: site
      kb.article.read: org
      ai.assistant.use: self
    denied:
      - crm.member.read
      - crm.member.write
      - crm.contact.read_sensitive
      - crm.export
      - opp.demand.read
      - lead.prospect.read
      - dash.site.read
      - dash.exec.read
      - iam.user.read
      - iam.role.assign
      - sys.config.manage
      - audit.log.read
"""

# ---------- app/permissions.py ----------
PERMISSIONS_PY = '''\
"""Probe routes: path param resolution happens at request time, so
require_permission must be invoked dynamically per-request.

FastAPI cannot use a path param as an argument to a dependency factory
at import time. Instead: dependency reads the resolved route path param
via request.path_params.
"""
import os
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request

from .tenant import TenantContext, get_tenant_context

PROBE_RECORDS = []  # populated by tests via fixture


@dataclass
class PermissionContext:
    code: str
    scope: str  # site | org | self
    ctx: TenantContext


def _check(code: str, ctx: TenantContext) -> PermissionContext:
    matrix = ctx.role_matrix.get("roles", ctx.role_matrix)
    entry = matrix.get(ctx.role, {}).get("allowed", {}).get(code)
    if entry is None:
        raise HTTPException(status_code=403, detail={"error": "permission_denied"})
    return PermissionContext(code=code, scope=entry, ctx=ctx)


def require_permission(code: str):
    """Static dependency for real routes (code known at import time)."""

    def dep(ctx: TenantContext = Depends(get_tenant_context)) -> PermissionContext:
        return _check(code, ctx)

    return dep


def _probe_dep(request: Request, ctx: TenantContext = Depends(get_tenant_context)) -> PermissionContext:
    code = request.path_params["code"]
    return _check(code, ctx)


def _visible_records(pctx: PermissionContext):
    """Apply data scope filtering to probe_records (site/org/self)."""
    ctx = pctx.ctx
    out = []
    for r in PROBE_RECORDS:
        if r["org_id"] != ctx.org_id:
            continue
        if pctx.scope == "site" and r["site_id"] != ctx.site_id:
            continue
        if pctx.scope == "self" and r["owner_id"] != ctx.user_id:
            continue
        out.append(r)
    return out


def probe_router():
    router = APIRouter(prefix="/__probe__")

    @router.get("/{code}")
    def probe(request: Request, pctx: PermissionContext = Depends(_probe_dep)):
        return {"ok": True, "code": request.path_params["code"]}

    @router.get("/{code}/records")
    def probe_records(request: Request, pctx: PermissionContext = Depends(_probe_dep)):
        items = _visible_records(pctx)
        return {"items": items, "total": len(items)}

    return router


def real_router():
    """Real (non-probe) IAM endpoints used by deny-list assertions."""
    router = APIRouter(prefix="/api/iam")

    @router.get("/users")
    def list_users(pctx: PermissionContext = Depends(require_permission("iam.user.read"))):
        return {"items": []}

    @router.post("/users/{user_id}/roles")
    def assign_role(user_id: str, pctx: PermissionContext = Depends(require_permission("iam.role.assign"))):
        return {"ok": True}

    return router


def mount_probe(app):
    if os.environ.get("APP_ENV") == "test":
        app.include_router(probe_router())
    app.include_router(real_router())
'''

# ---------- app/tenant.py ----------
TENANT_PY = '''\
"""Tenant context: org/site/user/role + role matrix access."""
from dataclasses import dataclass, replace

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class TenantContext:
    org_id: str
    user_id: str
    site_id: str
    role: str
    role_matrix: dict
    home_site_id: str = ""


def get_tenant_context(request: Request) -> TenantContext:
    state = getattr(request.app.state, "auth_state", None)
    if state is None:
        raise HTTPException(status_code=401, detail={"error": "unauthenticated"})
    ctx: TenantContext = state
    allowed_sites = ctx.role_matrix.get("_user_sites", {}).get(ctx.user_id, [ctx.home_site_id])
    requested_site = request.headers.get("X-Site-Id")
    if requested_site and requested_site != ctx.site_id:
        # switching site requires explicit membership (_user_sites seeded per employee)
        if requested_site not in allowed_sites:
            raise HTTPException(status_code=403, detail={"error": "permission_denied"})
        ctx = replace(ctx, site_id=requested_site)  # immutable: no cross-request leakage
    # membership guard: effective site must be in the employee's allowed set
    if ctx.site_id not in allowed_sites:
        raise HTTPException(status_code=403, detail={"error": "permission_denied"})
    return ctx
'''

# ---------- app/main.py ----------
MAIN_PY = '''\
"""App factory. Tests inject auth state directly (no real auth in this unit scope)."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .permissions import mount_probe


def create_app() -> FastAPI:
    app = FastAPI(title="member-space-platform (test slice)")

    @app.exception_handler(HTTPException)
    def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        # Platform contract: every 403 body is {"error": "permission_denied"}.
        content = {"error": "permission_denied"} if exc.status_code == 403 else exc.detail
        return JSONResponse(status_code=exc.status_code, content=content)

    mount_probe(app)
    return app
'''

# ---------- tests/conftest.py ----------
CONFTEST_PY = '''\
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
'''

# ---------- tests/test_front_desk.py ----------
TEST_PY = '''\
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
'''

# ---------- README.md ----------
README = '''\
# 3006 · front_desk 越权回归测试（S2-IAM-022）

## 运行

```bash
pip install fastapi httpx pytest pyyaml
APP_ENV=test pytest -v
```

## 覆盖

| 验收 | 用例 |
|------|------|
| 1 | `test_allowed_probe_200` ×9 参数化 + `test_denied_probe_403` ×12 参数化 + 真实接口 2 条 |
| 2 | 每个禁止项断言 `error == permission_denied` |
| 3 | `test_site_b_allows_become_403` ×9 参数化（X-Site-Id=会所 B） |
| 4 | `test_records_site_scope`：恰好 6 条会所 A 记录，会所 B 不泄漏 |

## 矩阵来源

`role_matrix.yml` 为种子（若平台已合并角色矩阵，则以平台为准替换 fixture）。允许项 9 个（7 site + 1 org + 1 self），禁止项 12 个权限点 + 2 个真实接口。

探针路由仅在 `APP_ENV=test` 挂载（`app/permissions.py: mount_probe`）。测试数据全部虚构。
'''

import os

d = r'C:\projects\ozon-monitor\clawhunt\pipeline\tasks\3006'
os.makedirs(d + '/app', exist_ok=True)
os.makedirs(d + '/tests', exist_ok=True)
open(d + '/role_matrix.yml', 'w', encoding='utf-8', newline='\n').write(ROLE_MATRIX)
open(d + '/app/__init__.py', 'w', encoding='utf-8', newline='\n').write('')
open(d + '/app/permissions.py', 'w', encoding='utf-8', newline='\n').write(PERMISSIONS_PY)
open(d + '/app/tenant.py', 'w', encoding='utf-8', newline='\n').write(TENANT_PY)
open(d + '/app/main.py', 'w', encoding='utf-8', newline='\n').write(MAIN_PY)
open(d + '/tests/__init__.py', 'w', encoding='utf-8', newline='\n').write('')
open(d + '/tests/conftest.py', 'w', encoding='utf-8', newline='\n').write(CONFTEST_PY)
open(d + '/tests/test_front_desk.py', 'w', encoding='utf-8', newline='\n').write(TEST_PY)
open(d + '/README.md', 'w', encoding='utf-8', newline='\n').write(README)
print('files written')
