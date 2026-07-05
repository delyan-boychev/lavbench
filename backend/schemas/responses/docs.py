"""Docs endpoint response models."""

from pydantic import BaseModel

from schemas.responses._base import RESPONSE_CONFIG


class DocContentResponse(BaseModel):
    title: str
    content: str

    model_config = RESPONSE_CONFIG
