import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from shared.common import get_user_manager

security = HTTPBearer()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    token = credentials.credentials
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT secret unavailable")

    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        user_id = payload.get("sub")
        exp = payload.get("exp")
        if not user_id or not exp:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

        if datetime.now(timezone.utc).timestamp() > float(exp):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

        user_manager = get_user_manager()
        user = user_manager.get_user(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        expiry_message = user_manager.enforce_deadline_for_user(user_id)
        if expiry_message:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"deadline_expired::{expiry_message}",
            )
        masquerader_id = payload.get("masquerader_id")
        if masquerader_id:
            return {**user, "masquerader_id": masquerader_id}
        return user
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
