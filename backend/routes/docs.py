import os
from flask import Blueprint, jsonify
from auth_utils import role_required

docs_bp = Blueprint('docs', __name__)

def read_doc_file(filename):
    paths = [
        os.path.join(os.path.dirname(__file__), '..', '..', filename),
        os.path.join(os.path.dirname(__file__), '..', filename),
        filename
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
    content = read_doc_file('student_guide.md')
    return jsonify({"title": "Student Guide", "content": content})

@docs_bp.route('/jury', methods=['GET'])
@role_required(['jury', 'admin'])
def get_jury_doc():
    content = read_doc_file('jury_guide.md')
    return jsonify({"title": "Jury Guide", "content": content})

@docs_bp.route('/admin', methods=['GET'])
@role_required(['admin'])
def get_admin_doc():
    content = read_doc_file('admin_guide.md')
    return jsonify({"title": "Admin Guide", "content": content})

@docs_bp.route('/api-reference', methods=['GET'])
@role_required(['admin'])
def get_api_ref_doc():
    content = read_doc_file('api_reference.md')
    return jsonify({"title": "API Reference", "content": content})
