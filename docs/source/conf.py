import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

# Autodoc imports backend/app.py which calls setup_logging; the Docker default
# LOG_DIR (/app/logs) is not writable on the host, so point it at a local dir.
os.environ.setdefault("LOG_DIR", os.path.join(os.path.dirname(__file__), "..", ".logs"))

# Use the full renderer: the default "httpdomain:old" only lists status codes,
# while "httpdomain" renders request/response JSON schemas and example bodies.
#
# The upstream option_spec defines some options with a None converter, which
# modern docutils treats as "explicitly disabled" (unknown option). Subclass
# the renderer to give those options real converters.
from sphinxcontrib.openapi.renderers import _httpdomain


class LavBenchHttpdomainRenderer(_httpdomain.HttpdomainRenderer):
    """HttpdomainRenderer with the None-converter options fixed."""

    option_spec = {
        **_httpdomain.HttpdomainRenderer.option_spec,
        "response-examples-for": lambda s: set(s.split()),
        "request-parameters-order": lambda s: s.split(),
        "example-preference": str,
        "request-example-preference": str,
        "response-example-preference": str,
    }


openapi_renderers = {"httpdomain:lavbench": LavBenchHttpdomainRenderer}
openapi_default_renderer = "httpdomain:lavbench"

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "dev_key_32charsMinForHMACKey!!")
os.environ.setdefault("ENCRYPTION_KEY", "M0uOruyloVEFHy1NgSleQ4dEvt7JZaJyZS8aOP3Xc_s=")

project = "LavBench"
copyright = "2026, Delyan Boychev & Bulgarian AI Olympiad Committee"
author = "Delyan Boychev & Bulgarian AI Olympiad Committee"
release = "1.0.0"

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
