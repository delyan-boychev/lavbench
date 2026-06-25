import json

EXTENSION_MAP = {
    ".ipynb": "notebook",
    ".csv": "csv",
    ".py": "python",
    ".parquet": "parquet",
    ".json": "json",
    ".txt": "text",
    ".tsv": "tsv",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
    ".pdf": "pdf",
    ".zip": "archive",
}

KNOWN_DANGEROUS_EXTENSIONS = {
    ".exe",
    ".com",
    ".bat",
    ".cmd",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".vbs",
    ".scr",
    ".jar",
    ".class",
    ".elf",
    ".dll",
    ".so",
    ".dylib",
    ".app",
    ".msi",
    ".bin",
}

KNOWN_DANGEROUS_MAGIC = [
    (b"MZ", "Windows executable"),
    (b"\x7fELF", "ELF binary"),
    (b"\xca\xfe\xba\xbe", "Java class"),
    (b"\x50\x4b\x03\x04", "ZIP archive"),
    (b"\x1f\x8b", "GZip archive"),
    (b"\x42\x5a\x68", "BZip2 archive"),
    (b"\x52\x61\x72\x21\x1a\x07", "RAR archive"),
    (b"\x25\x50\x44\x46", "PDF"),
    (b"\x89\x50\x4e\x47", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"#!", "Shebang script"),
]


def validate_extension(filename, allowed_extensions):
    """Case-insensitive extension check. Returns (is_valid, error_msg)."""
    if not filename or "." not in filename:
        return False, "Filename has no extension."
    ext = filename.rsplit(".", 1)[1].lower()
    dot_ext = "." + ext
    if dot_ext not in allowed_extensions:
        return (
            False,
            f"File extension '.{ext}' is not allowed. Allowed: {', '.join(allowed_extensions)}",
        )
    return True, None


def validate_mime_type(mimetype, allowed_mime_types):
    """Validate MIME type from request.files[].mimetype."""
    if not mimetype or mimetype == "application/octet-stream":
        return True, None
    if allowed_mime_types and mimetype not in allowed_mime_types:
        return False, f"MIME type '{mimetype}' is not allowed."
    return True, None


def validate_notebook_content(content_bytes):
    """Validate that content is a valid Jupyter Notebook JSON structure.
    Returns (is_valid, error_msg, parsed_notebook)."""
    try:
        text = content_bytes.decode("utf-8")
        notebook = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return False, f"Invalid JSON: {e}", None

    if not isinstance(notebook, dict):
        return False, "Notebook must be a JSON object.", None
    if "cells" in notebook and not isinstance(notebook["cells"], list):
        return False, "Notebook 'cells' must be an array.", None
    cells = notebook.get("cells", [])
    required_keys = {"cell_type", "source"}
    for i, cell in enumerate(cells):
        if not isinstance(cell, dict):
            return False, f"Cell at index {i} must be an object.", None
        if not required_keys.issubset(cell.keys()):
            missing = required_keys - cell.keys()
            return False, f"Cell at index {i} missing keys: {missing}", None
        if cell.get("cell_type") not in ("code", "markdown", "raw"):
            return (
                False,
                f"Cell at index {i} has invalid cell_type '{cell.get('cell_type')}'",
                None,
            )
    return True, None, notebook


def validate_csv_content(content_bytes):
    """Validate that content is valid CSV with text content."""
    try:
        text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return False, "CSV must be a UTF-8 encoded text file.", None
    if not text.strip():
        return False, "CSV file is empty.", None
    return True, None, text


def check_dangerous_magic(content_bytes):
    """Check file header bytes for known dangerous signatures.
    Returns (is_dangerous, description) or (False, None) if safe."""
    header = content_bytes[:8]
    for magic, desc in KNOWN_DANGEROUS_MAGIC:
        if header.startswith(magic):
            return True, desc
    return False, None


def check_dangerous_extension(filename):
    """Check if the filename has a known dangerous extension."""
    ext = "." + filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    return ext in KNOWN_DANGEROUS_EXTENSIONS
