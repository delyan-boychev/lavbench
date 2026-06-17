import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('CELERY_BROKER_URL', 'redis://localhost:6379/0')
os.environ.setdefault('SECRET_KEY', 'dev_key_32charsMinForHMACKey!!')
os.environ.setdefault('ENCRYPTION_KEY', 'M0uOruyloVEFHy1NgSleQ4dEvt7JZaJyZS8aOP3Xc_s=')

project = 'LavBench'
copyright = '2026, Bulgarian Team'
author = 'Bulgarian Team'
release = '1.0'

extensions = [
    'myst_parser',
    'sphinx_rtd_theme',
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinxcontrib.openapi',
]

templates_path = ['_templates']
exclude_patterns = []

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

myst_heading_anchors = 3
