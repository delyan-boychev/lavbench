"""Shared base configuration for all response models."""

from __future__ import annotations

from pydantic import ConfigDict

RESPONSE_CONFIG = ConfigDict(
    from_attributes=True,
)
