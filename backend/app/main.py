from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from backend.app.api.routes import router as identity_router

app = FastAPI(title="AI Film Studio Foundation API", version="1.5.0-dev.18")
app.include_router(identity_router)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response


app.add_middleware(SecurityHeadersMiddleware)
frontend_dir = Path(__file__).resolve().parents[2] / "frontend" / "control-center"
if frontend_dir.is_dir():
    app.mount("/control-center", StaticFiles(directory=str(frontend_dir), html=True), name="control-center")


@app.get("/health")
def health():
    return {"status": "ok", "service": "afs-foundation", "version": "1.5.0-dev.18"}
