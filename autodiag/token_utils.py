"""JWT encode/decode for result page tokens. No expiry — secret rotation invalidates old tokens."""

import os
from jose import jwt

_ALGORITHM = "HS256"


def encode_result_token(
    scores: dict,
    profile_key: str,
    felt_constraint: str,
    situation: str,
    response_id: str,
) -> str:
    payload = {
        "e": scores["energie"],
        "a": scores["attention"],
        "l": scores["liens"],
        "m": scores["moyens"],
        "profile": profile_key,
        "felt": felt_constraint,
        "situation": situation,
        "rid": response_id,
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=_ALGORITHM)


def decode_result_token(token: str) -> dict:
    return jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[_ALGORITHM])
