import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "dev_key_32charsMinForHMACKey!!")
os.environ.setdefault("ENCRYPTION_KEY", "M0uOruyloVEFHy1NgSleQ4dEvt7JZaJyZS8aOP3Xc_s=")

project = "LavBench"
copyright = "2026, Delyan Boychev & Bulgarian AI Olympiad Committee"
author = "Delyan Boychev & Bulgarian AI Olympiad Committee"
release = "0.2.1"

extensions = [
    "myst_parser",
    "sphinx_rtd_theme",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinxcontrib.openapi",
]

templates_path = ["_templates"]
exclude_patterns = []

html_theme = "sphinx_rtd_theme"
html_theme_options = {}
html_context = {
    "display_github": True,
    "github_user": "delyan-boychev",
    "github_repo": "lavbench",
    "github_version": "main",
    "conf_py_path": "/docs/source/",
}
html_static_path = ["_static"]
html_css_files = ["css/custom.css"]
html_logo = "_static/brand_logo_dark.svg"
html_favicon = "_static/logo.svg"
html_extra_path = ["robots.txt"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

myst_heading_anchors = 3
