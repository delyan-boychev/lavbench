from functools import wraps


def parse_json_body(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        from flask import request

        data = request.json or {}
        return f(data, *args, **kwargs)

    return wrapper
