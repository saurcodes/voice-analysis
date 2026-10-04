"""FastAPI dependencies: database session and the authenticated current user."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from vocal_coach.auth.jwt import AuthError, JWKSUnavailable, verify_token
from vocal_coach.storage import repo

bearer = HTTPBearer(auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


@dataclass
class CurrentUser:
    id: uuid.UUID
    sub: str
    email: str | None
    username: str | None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    settings = request.app.state.settings
    try:
        claims = verify_token(credentials.credentials, issuer=settings.keycloak_issuer,
                              audience=settings.keycloak_audience, jwks=request.app.state.jwks)
    except JWKSUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "authentication service unavailable")
    except AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {e}", headers={"WWW-Authenticate": "Bearer"})
    user = repo.upsert_user(session, claims["sub"], claims.get("email"), claims.get("preferred_username"))
    return CurrentUser(id=user.id, sub=user.keycloak_sub, email=user.email, username=user.username)
