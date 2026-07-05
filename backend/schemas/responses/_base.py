"""Shared base configuration for all response models."""

from pydantic import ConfigDict

RESPONSE_CONFIG = ConfigDict(
    from_attributes=True,
)
