from functools import wraps

from flask import request
from pydantic import BaseModel, ValidationError

from error_utils import err
from schemas.exceptions import SchemaError


def validate_json(schema_cls: type[BaseModel]):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            body = request.get_json(silent=True)
            if body is None:
                return err("ERR_VALIDATION", 422, message="Request body must be valid JSON.")
            try:
                validated = schema_cls(**body)
                kwargs["data"] = validated
            except ValidationError as e:
                return _validation_error(e)
            return f(*args, **kwargs)

        return wrapper

    return decorator


def validate_form(schema_cls: type[BaseModel]):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                validated = schema_cls(**request.form.to_dict())
                kwargs["form_data"] = validated
            except ValidationError as e:
                return _validation_error(e)
            return f(*args, **kwargs)

        return wrapper

    return decorator


def _validation_error(e: ValidationError):
    details = []
    specific_code = None
    for err_item in e.errors():
        field = " \u2192 ".join(str(loc) for loc in err_item["loc"])
        ctx = err_item.get("ctx", {})
        error_obj = ctx.get("error")
        if isinstance(error_obj, SchemaError):
            if specific_code is None:
                specific_code = error_obj.code
            details.append(f"{field}: {error_obj.message}")
        else:
            details.append(f"{field}: {err_item['msg']}")
    if specific_code:
        return err(specific_code, 422, message="; ".join(details))
    return err("ERR_VALIDATION", 422, message="; ".join(details))
