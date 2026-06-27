import contextlib
import os
import shutil

from werkzeug.utils import secure_filename


def safe_save_file(uploaded_file, directory, filename=None):
    os.makedirs(directory, exist_ok=True)
    safe_name = secure_filename(filename) if filename else secure_filename(uploaded_file.filename)
    save_path = os.path.join(directory, safe_name)
    uploaded_file.save(save_path)
    return save_path


def cleanup_paths(paths):
    for p in paths:
        if p and os.path.exists(p):
            with contextlib.suppress(OSError):
                os.remove(p)


def remove_if_exists(path):
    if path and os.path.exists(path):
        with contextlib.suppress(OSError):
            os.remove(path)


def rmtree_ignore(path):
    if path and os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
