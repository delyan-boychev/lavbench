import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.submission_service import (
    check_execution_rules,
    extract_code_from_cells,
    extract_code_from_notebook,
)


class TestExtractCodeFromCells:
    def test_empty_list(self):
        assert extract_code_from_cells([]) == []

    def test_none_input(self):
        assert extract_code_from_cells(None) == []

    def test_dict_cell_with_list_source(self):
        cells = [{"source": ["print('hello')", "print('world')"]}]
        result = extract_code_from_cells(cells)
        assert result == ["print('hello')print('world')"]

    def test_dict_cell_with_string_source(self):
        cells = [{"source": "print('hello')"}]
        result = extract_code_from_cells(cells)
        assert result == ["print('hello')"]

    def test_string_cell(self):
        cells = ["print('hello')"]
        result = extract_code_from_cells(cells)
        assert result == ["print('hello')"]

    def test_mixed_cells(self):
        cells = [{"source": ["a = 1"]}, "b = 2", {"source": ["c = 3"]}]
        result = extract_code_from_cells(cells)
        assert len(result) == 3

    def test_non_dict_non_string_cell(self):
        cells = [42]
        result = extract_code_from_cells(cells)
        assert result == ["42"]

    def test_missing_source_key(self):
        cells = [{"not_source": "hello"}]
        result = extract_code_from_cells(cells)
        assert result == [""]


class TestExtractCodeFromNotebook:
    def test_valid_notebook(self):
        nb = {
            "cells": [
                {"cell_type": "code", "source": ["print('hello')"]},
                {"cell_type": "markdown", "source": ["# comment"]},
                {"cell_type": "code", "source": ["x = 1"]},
            ]
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            assert len(result) == 2
            assert result[0] == "print('hello')"
            assert result[1] == "x = 1"
        finally:
            os.unlink(fpath)

    def test_no_code_cells(self):
        nb = {"cells": [{"cell_type": "markdown", "source": ["# only comments"]}]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            assert result == []
        finally:
            os.unlink(fpath)

    def test_missing_cells_key(self):
        nb = {"metadata": {}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            assert result == []
        finally:
            os.unlink(fpath)

    def test_malformed_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False) as f:
            f.write("not json")
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            assert result == []
        finally:
            os.unlink(fpath)

    def test_file_not_found(self):
        result = extract_code_from_notebook("/nonexistent/path.ipynb")
        assert result == []

    def test_code_cell_with_string_source(self):
        nb = {"cells": [{"cell_type": "code", "source": "print('hello')"}]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            assert result == ["print('hello')"]
        finally:
            os.unlink(fpath)

    def test_list_as_cells_value(self):
        nb = {"cells": "not a list"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ipynb", delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            assert result == []
        finally:
            os.unlink(fpath)


class MockTask:
    def __init__(self):
        self.ban_magic_commands = False
        self.banned_imports = ""
        self.whitelisted_imports = ""


class TestCheckExecutionRulesAST:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.task = MockTask()

    def test_allowed_code(self):
        ok, msg = check_execution_rules(self.task, ["x = 1\ny = x + 2\nprint(y)"])
        assert ok is True
        assert msg is None

    def test_banned_exec(self):
        ok, msg = check_execution_rules(self.task, ["exec('print(1)')"])
        assert ok is False
        assert "exec" in msg

    def test_banned_eval(self):
        ok, msg = check_execution_rules(self.task, ["eval('1 + 1')"])
        assert ok is False
        assert "eval" in msg

    def test_banned_compile(self):
        ok, msg = check_execution_rules(self.task, ["compile('print(1)', '<string>', 'exec')"])
        assert ok is False
        assert "compile" in msg

    def test_banned_importlib(self):
        ok, msg = check_execution_rules(self.task, ["import importlib"])
        assert ok is False
        assert "importlib" in msg

    def test_banned_builtins_lookup(self):
        ok, msg = check_execution_rules(self.task, ["__builtins__.__dict__['eval']('1')"])
        assert ok is False
        assert "eval" in msg

    def test_obfuscated_exec_dict(self):
        ok, msg = check_execution_rules(self.task, ["globals()['exec']('print(1)')"])
        assert ok is False
        assert "exec" in msg

    def test_syntax_error_fallback(self):
        ok, msg = check_execution_rules(self.task, ["if True eval("])
        assert ok is False
        assert "eval" in msg

    def test_allowed_attributes(self):
        # Verify model.eval() and re.compile(...) are allowed
        ok, msg = check_execution_rules(self.task, ["model.eval()\nre.compile('abc')"])
        assert ok is True
        assert msg is None

    def test_banned_meta_programming(self):
        # Verify subclass sandbox escape attribute is blocked
        ok, msg = check_execution_rules(self.task, ["().__class__.__bases__[0].__subclasses__()"])
        assert ok is False
        assert "subclasses" in msg.lower()

    def test_ban_magic_commands_enabled(self):
        self.task.ban_magic_commands = True
        ok, msg = check_execution_rules(self.task, ["!pip install requests"])
        assert ok is False
        assert "magic commands" in msg

        ok, msg = check_execution_rules(self.task, ["%matplotlib inline"])
        assert ok is False
        assert "magic commands" in msg

    def test_ban_magic_commands_disabled(self):
        self.task.ban_magic_commands = False
        ok, msg = check_execution_rules(self.task, ["!pip install requests\n%matplotlib inline"])
        assert ok is True
        assert msg is None

    def test_banned_imports_simple(self):
        self.task.banned_imports = "os,sys,subprocess"
        ok, msg = check_execution_rules(self.task, ["import os"])
        assert ok is False
        assert "Import of library 'os' is banned" in msg

        ok, msg = check_execution_rules(self.task, ["from subprocess import Popen"])
        assert ok is False
        assert "Import from library 'subprocess' is banned" in msg

    def test_banned_imports_submodule(self):
        self.task.banned_imports = "os,sys,subprocess"
        ok, msg = check_execution_rules(self.task, ["import os.path"])
        assert ok is False
        assert "Import of library 'os.path' is banned" in msg

    def test_banned_imports_not_triggered(self):
        self.task.banned_imports = "subprocess"
        ok, msg = check_execution_rules(self.task, ["import json\nimport numpy as np"])
        assert ok is True
        assert msg is None

    def test_whitelisted_imports_allowed(self):
        self.task.whitelisted_imports = "json,numpy,pandas"
        ok, msg = check_execution_rules(self.task, ["import json\nfrom numpy import array"])
        assert ok is True
        assert msg is None

    def test_whitelisted_imports_disallowed(self):
        self.task.whitelisted_imports = "json,numpy"
        ok, msg = check_execution_rules(self.task, ["import requests"])
        assert ok is False
        assert "Import of library 'requests' is not allowed by whitelist" in msg

        ok, msg = check_execution_rules(self.task, ["from pandas import DataFrame"])
        assert ok is False
        assert "Import from library 'pandas' is not allowed by whitelist" in msg

    def test_magic_commands_inside_string_or_comment(self):
        self.task.ban_magic_commands = True

        # Valid python code with lines starting with % or ! inside comments or string literals
        code1 = "#%matplotlib inline\nprint('hello')"
        ok, msg = check_execution_rules(self.task, [code1])
        assert ok is True, f"Banned error: {msg}"

        code2 = 'query = """\n%select * from users;\n"""'
        ok, msg = check_execution_rules(self.task, [code2])
        assert ok is True, f"Banned error: {msg}"

        code3 = "css_string = 'div { content: !important; }'"
        ok, msg = check_execution_rules(self.task, [code3])
        assert ok is True, f"Banned error: {msg}"
