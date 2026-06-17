# Minimal makefile for Sphinx documentation
#

SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = build
SCRIPTSDIR    = scripts

# Detect micromamba env — use it if available, else fall back to pip
LBCMD = micromamba run -n lavbench_backend $(SPHINXBUILD)
PYCMD = micromamba run -n lavbench_backend python3
ifeq (, $(shell which micromamba 2>/dev/null))
  LBCMD = $(SPHINXBUILD)
  PYCMD = python3
endif

.PHONY: help clean html livehtml fetch-spec

help:
	@$(LBCMD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)

clean:
	rm -rf $(BUILDDIR)/* $(SOURCEDIR)/api/spec_*.json

fetch-spec:
	@$(PYCMD) $(SCRIPTSDIR)/_generate_api_spec.py

html: fetch-spec
	@$(LBCMD) -b html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)

livehtml: fetch-spec
	@$(LBCMD) -b html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) -a -E --watch "$(SOURCEDIR)"
