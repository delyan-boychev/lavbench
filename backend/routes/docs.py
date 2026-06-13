import os
from flask import Blueprint, jsonify, request
from auth_utils import role_required

docs_bp = Blueprint('docs', __name__)

def get_request_lang():
    # 1. Query parameter
    lang = request.args.get('lang')
    
    # 2. Accept-Language header
    if not lang:
        accept_lang = request.headers.get('Accept-Language')
        if accept_lang:
            parts = [p.strip() for p in accept_lang.split(',')]
            if parts:
                lang = parts[0].split(';')[0].strip()
                
    if not lang:
        return 'en'
        
    lang = lang.split('-')[0].split('_')[0].strip().lower()
    if lang not in ('en', 'bg'):
        return 'en'
        
    return lang

def read_doc_file(filename, lang='en'):
    # We will try the requested language first, then fallback to 'en'
    langs_to_try = [lang]
    if lang != 'en':
        langs_to_try.append('en')
        
    for l in langs_to_try:
        paths = [
            os.path.join(os.path.dirname(__file__), '..', '..', 'guides', l, filename),
            os.path.join(os.path.dirname(__file__), '..', 'guides', l, filename),
            os.path.join('guides', l, filename)
        ]
        for p in paths:
            abs_p = os.path.abspath(p)
            if os.path.exists(abs_p):
                try:
                    with open(abs_p, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception as e:
                    return f"Error reading documentation file: {str(e)}"
                    
    return "Documentation file not found."

@docs_bp.route('/student', methods=['GET'])
@role_required(['competitor', 'jury', 'admin'])
def get_student_doc():
    lang = get_request_lang()
    content = read_doc_file('student_guide.md', lang)
    title = {
        'bg': "Ръководство за ученика",
        'en': "Student Guide"
    }.get(lang, "Student Guide")
    return jsonify({"title": title, "content": content})

@docs_bp.route('/jury', methods=['GET'])
@role_required(['jury', 'admin'])
def get_jury_doc():
    lang = get_request_lang()
    content = read_doc_file('jury_guide.md', lang)
    title = {
        'bg': "Ръководство за журито",
        'en': "Jury Guide"
    }.get(lang, "Jury Guide")
    return jsonify({"title": title, "content": content})

@docs_bp.route('/admin', methods=['GET'])
@role_required(['admin'])
def get_admin_doc():
    lang = get_request_lang()
    content = read_doc_file('admin_guide.md', lang)
    title = {
        'bg': "Админ ръководство",
        'en': "Admin Guide"
    }.get(lang, "Admin Guide")
    return jsonify({"title": title, "content": content})

@docs_bp.route('/api-reference', methods=['GET'])
@role_required(['admin'])
def get_api_ref_doc():
    lang = get_request_lang()
    content = read_doc_file('api_reference.md', lang)
    title = {
        'bg': "API Справка",
        'en': "API Reference"
    }.get(lang, "API Reference")
    return jsonify({"title": title, "content": content})
