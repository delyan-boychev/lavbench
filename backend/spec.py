"""Shared spectree SpecTree instance for route decorators + OpenAPI generation."""

from __future__ import annotations

from typing import Any

from spectree import SpecTree
from spectree.models import InType, SecureType, SecurityScheme, SecuritySchemeData


def _validation_before_handler(
    req: Any, resp: Any, req_validation_error: Any, instance: Any
) -> None:
    """Reformat validation errors to project convention."""
    if req_validation_error is not None and resp is not None:
        from schemas import _format_validation_error_for_response

        _format_validation_error_for_response(resp, req_validation_error)


api = SpecTree(
    "flask",
    before=_validation_before_handler,
    title="LavBench API",
    version="1.0",
    description="Machine Learning Competition Platform — REST + SSE Endpoints",
    openapi_version="3.0.3",
    security_schemes=[
        SecurityScheme(
            name="cookieAuth",
            data=SecuritySchemeData(
                type=SecureType.API_KEY,
                name="auth_token",
                **{"in": InType.COOKIE},
                description="Session cookie required for most endpoints.",
            ),
        ),
    ],
)
