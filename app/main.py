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
