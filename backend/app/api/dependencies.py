from __future__ import annotations
from typing import Generator
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from backend.app.db.session import SessionLocal
from backend.app.models import Principal
from backend.app.security.tokens import AuthenticationError, authenticate_api_token

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="AFS bearer token")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="bearer authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        return authenticate_api_token(db, credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc
