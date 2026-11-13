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
