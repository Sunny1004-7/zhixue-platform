from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuthSession, User
from .security import hash_token


bearer_scheme = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.db.session_factory()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]


def current_session_and_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> tuple[AuthSession, User]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    result = db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.token_hash == hash_token(credentials.credentials))
    ).first()
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态无效")
    auth_session, user = result
    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if auth_session.revoked_at is not None or expires_at <= datetime.now(timezone.utc) or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已过期")
    return auth_session, user


def get_current_user(pair: Annotated[tuple[AuthSession, User], Depends(current_session_and_user)]) -> User:
    return pair[1]


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(role: str):
    def dependency(user: CurrentUser) -> User:
        if user.role != role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前身份无权访问此空间")
        return user
    return dependency


StudentUser = Annotated[User, Depends(require_role("student"))]
TeacherUser = Annotated[User, Depends(require_role("teacher"))]
