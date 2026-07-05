from __future__ import annotations

from typing import Any

from flask import Request

from config import Config


def extract_pagination(
    request: Request, default_per_page: int | None = None, max_per_page: int | None = None
) -> tuple[int, int]:
    default_per_page = default_per_page or Config.DEFAULT_PER_PAGE
    max_per_page = max_per_page or Config.MAX_PER_PAGE
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", default_per_page, type=int), max_per_page)
    return page, per_page


def paginated_response(items: list[Any], total: int, page: int, pages: int) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": pages,
    }
