def extract_pagination(request, default_per_page=10, max_per_page=100):
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", default_per_page, type=int), max_per_page)
    return page, per_page


def paginated_response(items, total, page, pages):
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": pages,
    }
