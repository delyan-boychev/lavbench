import os
import sys
import json
import unittest
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.submission_service import (
    extract_code_from_cells, extract_code_from_notebook,
    check_execution_rules, calculate_submission_priority,
    get_best_submission
)


class TestExtractCodeFromCells(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(extract_code_from_cells([]), [])

    def test_none_input(self):
        self.assertEqual(extract_code_from_cells(None), [])

    def test_dict_cell_with_list_source(self):
        cells = [{"source": ["print('hello')", "print('world')"]}]
        result = extract_code_from_cells(cells)
        self.assertEqual(result, ["print('hello')print('world')"])

    def test_dict_cell_with_string_source(self):
        cells = [{"source": "print('hello')"}]
        result = extract_code_from_cells(cells)
        self.assertEqual(result, ["print('hello')"])

    def test_string_cell(self):
        cells = ["print('hello')"]
        result = extract_code_from_cells(cells)
        self.assertEqual(result, ["print('hello')"])

    def test_mixed_cells(self):
        cells = [
            {"source": ["a = 1"]},
            "b = 2",
            {"source": ["c = 3"]}
        ]
        result = extract_code_from_cells(cells)
        self.assertEqual(len(result), 3)

    def test_non_dict_non_string_cell(self):
        cells = [42]
        result = extract_code_from_cells(cells)
        self.assertEqual(result, ["42"])

    def test_missing_source_key(self):
        cells = [{"not_source": "hello"}]
        result = extract_code_from_cells(cells)
        self.assertEqual(result, [""])


class TestExtractCodeFromNotebook(unittest.TestCase):
    def test_valid_notebook(self):
        nb = {
            "cells": [
                {"cell_type": "code", "source": ["print('hello')"]},
                {"cell_type": "markdown", "source": ["# comment"]},
                {"cell_type": "code", "source": ["x = 1"]}
            ]
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ipynb', delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0], "print('hello')")
            self.assertEqual(result[1], "x = 1")
        finally:
            os.unlink(fpath)

    def test_no_code_cells(self):
        nb = {"cells": [{"cell_type": "markdown", "source": ["# only comments"]}]}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ipynb', delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            self.assertEqual(result, [])
        finally:
            os.unlink(fpath)

    def test_missing_cells_key(self):
        nb = {"metadata": {}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ipynb', delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            self.assertEqual(result, [])
        finally:
            os.unlink(fpath)

    def test_malformed_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ipynb', delete=False) as f:
            f.write("not json")
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            self.assertEqual(result, [])
        finally:
            os.unlink(fpath)

    def test_file_not_found(self):
        result = extract_code_from_notebook("/nonexistent/path.ipynb")
        self.assertEqual(result, [])

    def test_code_cell_with_string_source(self):
        nb = {"cells": [{"cell_type": "code", "source": "print('hello')"}]}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ipynb', delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            self.assertEqual(result, ["print('hello')"])
        finally:
            os.unlink(fpath)

    def test_list_as_cells_value(self):
        nb = {"cells": "not a list"}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ipynb', delete=False) as f:
            json.dump(nb, f)
            fpath = f.name
        try:
            result = extract_code_from_notebook(fpath)
            self.assertEqual(result, [])
        finally:
            os.unlink(fpath)
