"""Auth endpoint response models."""

from pydantic import BaseModel

from schemas.responses._base import RESPONSE_CONFIG
from schemas.responses.admin import UserResponse


class LoginResponse(BaseModel):
    message: str
    user: UserResponse

    model_config = RESPONSE_CONFIG


class CurrentUserResponse(BaseModel):
    user: UserResponse

    model_config = RESPONSE_CONFIG


class CsrfTokenResponse(BaseModel):
    csrf_token: str

    model_config = RESPONSE_CONFIG


class LogoutResponse(BaseModel):
    message: str

    model_config = RESPONSE_CONFIG
