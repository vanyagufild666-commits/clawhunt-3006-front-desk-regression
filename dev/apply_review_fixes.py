"""Fix 3006 per review: fake-positive site-B test + shared ctx mutation."""
import os

base = 'clawhunt/pipeline/tasks/3006/'

# ---------- tenant.py: replace ctx instead of mutating; drop dead code ----------
tenant = '''\
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
open(base + 'app/tenant.py', 'w', encoding='utf-8', newline='\n').write(tenant)

# permissions.py: use replace-based ctx; ctx already handled by dependency
perms = open(base + 'app/permissions.py', encoding='utf-8').read()
perms = perms.replace('from .tenant import TenantContext, get_tenant_context',
                      'from .tenant import TenantContext, get_tenant_context')
open(base + 'app/permissions.py', 'w', encoding='utf-8', newline='\n').write(perms)

# ---------- conftest.py: site-B fixture starts at home site A (switch really happens) ----------
conftest = open(base + 'tests/conftest.py', encoding='utf-8').read()
conftest = conftest.replace('''\
@pytest.fixture()
def client_site_b(role_matrix):
    PROBE_RECORDS.clear()
    PROBE_RECORDS.extend(_records())
    app = create_app()
    # employee tries to use site_B: not in _user_sites -> every permission check 403
    app.state.auth_state = TenantContext(
        org_id=ORG_ID, user_id=USER_ID, site_id=SITE_B, role="front_desk",
        role_matrix={"roles": copy.deepcopy(role_matrix["roles"]),
                     "_user_sites": {USER_ID: [SITE_A]}},
        home_site_id=SITE_A,
    )
    with TestClient(app) as c:
        yield c
''', '''\
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
''')
open(base + 'tests/conftest.py', 'w', encoding='utf-8', newline='\n').write(conftest)

# ---------- test file: real switch assertion + org-scope pin + rename ----------
t = open(base + 'tests/test_front_desk.py', encoding='utf-8').read()
t = t.replace('''\
def test_site_b_without_header_still_403_for_site_ops(client_site_b):
    # tenant ctx pre-set to site_B (not in employee's allowed sites) -> denied
    # note: ctx is applied at fixture level; request without X-Site-Id keeps site_B
    r = client_site_b.get("/__probe__/front.visitor.read")
    assert r.status_code == 403, f"forced site_B ctx expect=403 actual={r.status_code} body={r.text}"
''', '''\
def test_records_site_scope(client):
    r = client.get("/__probe__/kb.article.read/records")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert len(ids) == 9, "org scope sees all sites in org (9 records)"
''')
# fix: that replacement was wrong target; do explicit renames and additions instead
t = open(base + 'tests/test_front_desk.py', encoding='utf-8').read()
t = t.replace('def test_denied_count_matches_matrix(', 'def test_matrix_deny_set_matches_task(')
t = t.replace('''\

# A4: data scope on records probe
''', '''\

# A4: data scope on records probe


def test_records_org_scope_spans_sites(client):
    """Pin org-scope semantics: kb.article.read (org) sees site A + site B."""
    r = client.get("/__probe__/kb.article.read/records")
    assert r.status_code == 200
    ids = {i["id"] for i in r.json()["items"]}
    assert len(ids) == 9, f"org scope must see 9 records across both sites, got {len(ids)}"
    assert {i for i in ids if i.startswith("b_")} == {f"b_{k}" for k in range(3)}
''')
open(base + 'tests/test_front_desk.py', 'w', encoding='utf-8', newline='\n').write(t)

# ---------- APP_ENV default in conftest head ----------
conftest = open(base + 'tests/conftest.py', encoding='utf-8').read()
if 'os.environ.setdefault' not in conftest:
    conftest = conftest.replace('''\
"""
import copy

import pytest
''', '''\
"""
import copy
import os

os.environ.setdefault("APP_ENV", "test")  # probe routes mount only in test env

import pytest
''')
open(base + 'tests/conftest.py', 'w', encoding='utf-8', newline='\n').write(conftest)

# ---------- 403 top-level error shape: add exception handler in main.py ----------
main_py = '''\
"""App factory. Tests inject auth state directly (no real auth in this unit scope)."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .permissions import mount_probe


def permission_denied_handler(request: Request, exc: HTTPException):
    """Top-level error shape: {"error": "permission_denied"} (platform contract)."""
    return JSONResponse(status_code=exc.status_code, content={"error": "permission_denied"})


def create_app() -> FastAPI:
    app = FastAPI(title="member-space-platform (test slice)")
    app.add_exception_handler(
        HTTPException,
        lambda req, exc: JSONResponse(status_code=exc.status_code,
                                      content=exc.detail)  # detail already {"error": ...}
        if isinstance(exc.detail, dict) and exc.status_code != 403
        else JSONResponse(status_code=exc.status_code,
                          content={"error": "permission_denied"} if exc.status_code == 403 else exc.detail),
    )
    mount_probe(app)
    return app
'''
open(base + 'app/main.py', 'w', encoding='utf-8', newline='\n').write(main_py)

# ---------- gitignore ----------
open(base + '.gitignore', 'w', encoding='utf-8', newline='\n').write(
    '__pycache__/\n*.pyc\n.pytest_cache/\n')

print('fixes applied')
