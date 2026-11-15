"""Tests for the file validation service."""

import json

from services.file_validation import (
    check_dangerous_extension,
    validate_csv_content,
    validate_extension,
    validate_notebook_content,
)


class TestValidateExtension:
    def test_allowed_extension(self):
        valid, error = validate_extension("notebook.ipynb", {".ipynb", ".csv"})
        assert valid is True
        assert error is None

    def test_disallowed_extension(self):
        valid, error = validate_extension("script.exe", {".ipynb", ".csv"})
        assert valid is False
        assert "not allowed" in error

    def test_no_extension(self):
        valid, error = validate_extension("README", {".md", ".txt"})
        assert valid is False
        assert "no extension" in error

    def test_no_filename(self):
        valid, error = validate_extension("", {".txt"})
        assert valid is False
        assert "no extension" in error

    def test_none_filename(self):
        valid, error = validate_extension(None, {".txt"})
        assert valid is False
        assert "no extension" in error

    def test_case_insensitive(self):
        valid, error = validate_extension("DATA.CSV", {".csv"})
        assert valid is True
        assert error is None

    def test_multiple_dots(self):
        valid, error = validate_extension("archive.tar.gz", {".gz"})
        assert valid is True
        assert error is None

    def test_empty_allowed_set(self):
        valid, _error = validate_extension("file.py", set())
        assert valid is False


class TestValidateNotebookContent:
    def test_valid_notebook(self):
        content = json.dumps(
            {
                "cells": [
                    {"cell_type": "code", "source": ["print('hello')"]},
                    {"cell_type": "markdown", "source": ["# Title"]},
                ]
            }
        ).encode()
        valid, error, notebook = validate_notebook_content(content)
        assert valid is True
        assert error is None
        assert notebook is not None

    def test_invalid_json(self):
        valid, error, notebook = validate_notebook_content(b"not json")
        assert valid is False
        assert "Invalid JSON" in error
        assert notebook is None

    def test_not_a_dict(self):
        valid, error, notebook = validate_notebook_content(b"[]")
        assert valid is False
        assert "JSON object" in error
        assert notebook is None

    def test_cells_not_a_list(self):
        content = json.dumps({"cells": "not_a_list"}).encode()
        valid, error, _notebook = validate_notebook_content(content)
        assert valid is False
        assert "cells" in error.lower()

    def test_cell_missing_required_keys(self):
        content = json.dumps({"cells": [{"cell_type": "code"}]}).encode()
        valid, error, _notebook = validate_notebook_content(content)
        assert valid is False
        assert "missing keys" in error

    def test_cell_invalid_type(self):
        content = json.dumps({"cells": [{"cell_type": "unknown", "source": []}]}).encode()
        valid, error, _notebook = validate_notebook_content(content)
        assert valid is False
        assert "invalid cell_type" in error

    def test_cell_not_an_object(self):
        content = json.dumps({"cells": ["string_cell"]}).encode()
        valid, error, _notebook = validate_notebook_content(content)
        assert valid is False
        assert "must be an object" in error

    def test_no_cells_key(self):
        content = json.dumps({"nbformat": 4}).encode()
        valid, _error, notebook = validate_notebook_content(content)
        assert valid is True  # Notebooks without cells key are valid (empty notebook)
        assert notebook is not None

    def test_empty_cells(self):
        content = json.dumps({"cells": []}).encode()
        valid, _error, _notebook = validate_notebook_content(content)
        assert valid is True

    def test_unicode_decode_error(self):
        valid, error, _notebook = validate_notebook_content(b"\xff\xfe\x00")
        assert valid is False
        assert "Invalid JSON" in error or "decode" in error.lower()


class TestValidateCsvContent:
    def test_valid_csv(self):
        content = b"col1,col2\nval1,val2\n"
        valid, error, text = validate_csv_content(content)
        assert valid is True
        assert error is None
        assert text == "col1,col2\nval1,val2\n"

    def test_empty_csv(self):
        valid, error, _text = validate_csv_content(b"")
        assert valid is False
        assert "empty" in error

    def test_whitespace_only_csv(self):
        valid, error, _text = validate_csv_content(b"   \n  ")
        assert valid is False
        assert "empty" in error

    def test_binary_content(self):
        valid, error, _text = validate_csv_content(b"\xff\xfe\x00\x01")
        assert valid is False
        assert "UTF-8" in error


class TestCheckDangerousExtension:
    def test_exe(self):
        assert check_dangerous_extension("virus.exe") is True

    def test_bat(self):
        assert check_dangerous_extension("script.bat") is True

    def test_sh(self):
        assert check_dangerous_extension("script.sh") is True

    def test_dll(self):
        assert check_dangerous_extension("library.dll") is True

    def test_safe_extension(self):
        assert check_dangerous_extension("file.ipynb") is False

    def test_safe_csv(self):
        assert check_dangerous_extension("data.csv") is False

    def test_no_extension(self):
        assert check_dangerous_extension("README") is False

    def test_empty_filename(self):
        assert check_dangerous_extension("") is False

    def test_case_insensitive(self):
        assert check_dangerous_extension("virus.EXE") is True
        assert check_dangerous_extension("virus.Bat") is True

    def test_hidden_dangerous(self):
        assert check_dangerous_extension(".bat") is True  # Just the extension as "filename"
