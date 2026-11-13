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
