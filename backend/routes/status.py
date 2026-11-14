"""Route handlers for the status blueprint: public status and the admin system status."""

from __future__ import annotations

from flask import Blueprint
from spectree import Response

from schemas.responses import ErrorResponse, PublicStatusResponse, SystemStatusResponse
from services.status_service import public_status, system_status
from utils.auth_utils import login_required, role_required
from utils.spec import api

status_bp = Blueprint("status", __name__)


@status_bp.route("/status", methods=["GET"])
@api.validate(resp=Response(HTTP_200=PublicStatusResponse), tags=["Status"])
def get_public_status() -> PublicStatusResponse:
    """Coarse service status in Statuspage component words. No login required."""
    return PublicStatusResponse.model_validate(public_status())


@status_bp.route("/admin/system-status", methods=["GET"])
@login_required
@role_required(["admin", "jury"])
@api.validate(
    resp=Response(HTTP_200=SystemStatusResponse, HTTP_401=ErrorResponse, HTTP_403=ErrorResponse),
    tags=["Admin"],
    security=[{"cookieAuth": []}],
)
def get_system_status() -> SystemStatusResponse:
    """Per-queue consumers, worker heartbeats and submission counts (admin and jury)."""
    return SystemStatusResponse.model_validate(system_status())
