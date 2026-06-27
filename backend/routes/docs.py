import os

from auth_utils import role_required
from flask import Blueprint, jsonify, request

docs_bp = Blueprint("docs", __name__)


def get_request_lang():
    # 1. Query parameter
    lang = request.args.get("lang")

    # 2. Accept-Language header
    if not lang:
        accept_lang = request.headers.get("Accept-Language")
        if accept_lang:
            parts = [p.strip() for p in accept_lang.split(",")]
            if parts:
                lang = parts[0].split(";")[0].strip()

    if not lang:
        return "en"

    lang = lang.split("-")[0].split("_")[0].strip().lower()
    if lang not in ("en", "bg"):
        return "en"

    return lang


def read_doc_file(filename, lang="en"):
    # We will try the requested language first, then fallback to 'en'
    langs_to_try = [lang]
    if lang != "en":
        langs_to_try.append("en")

    # Determine guides base directory and ensure we never escape it
    guides_base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "guides"))

    for lng in langs_to_try:
        safe_path = os.path.abspath(os.path.join(guides_base, lng, filename))
        # Verify the resolved path stays within guides_base
        if os.path.commonpath([safe_path, guides_base]) != guides_base:
            continue
        if os.path.isfile(safe_path):
            try:
                with open(safe_path, encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                return f"Error reading documentation file: {e!s}"

    return "Documentation file not found."


@docs_bp.route("/student", methods=["GET"])
@role_required(["competitor", "jury", "admin"])
def get_student_doc():
    """
    Get the student documentation guide.
    ---
    tags:
      - Docs
    security:
      - cookieAuth: []
    parameters:
      - in: query
        name: lang
        type: string
        required: false
        description: Language code (e.g. 'en', 'bg')
    responses:
      200:
        description: Returns the rendered guide

        content:
          application/json:
            schema:
              type: object
    """
    lang = get_request_lang()
    content = read_doc_file("student_guide.md", lang)
    title = {"bg": "Ръководство за ученика", "en": "Student Guide"}.get(lang, "Student Guide")
    return jsonify({"title": title, "content": content})


@docs_bp.route("/jury", methods=["GET"])
@role_required(["jury", "admin"])
def get_jury_doc():
    """
    Get the jury documentation guide.
    ---
    tags:
      - Docs
    security:
      - cookieAuth: []
    parameters:
      - in: query
        name: lang
        type: string
        required: false
        description: Language code (e.g. 'en', 'bg')
    responses:
      200:
        description: Returns the rendered guide

        content:
          application/json:
            schema:
              type: object
    """
    lang = get_request_lang()
    content = read_doc_file("jury_guide.md", lang)
    title = {"bg": "Ръководство за журито", "en": "Jury Guide"}.get(lang, "Jury Guide")
    return jsonify({"title": title, "content": content})


@docs_bp.route("/admin", methods=["GET"])
@role_required(["admin"])
def get_admin_doc():
    """
    Get the admin documentation guide.
    ---
    tags:
      - Docs
    security:
      - cookieAuth: []
    parameters:
      - in: query
        name: lang
        type: string
        required: false
        description: Language code (e.g. 'en', 'bg')
    responses:
      200:
        description: Returns the rendered guide

        content:
          application/json:
            schema:
              type: object
    """
    lang = get_request_lang()
    content = read_doc_file("admin_guide.md", lang)
    title = {"bg": "Админ ръководство", "en": "Admin Guide"}.get(lang, "Admin Guide")
    return jsonify({"title": title, "content": content})
