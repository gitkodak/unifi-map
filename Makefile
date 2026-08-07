.PHONY: help check format lint test map fetch render tree offline dark demo \
        demo-dark demo-overrides demo-images demo-snapshot docs build clean

VENV  := .venv
PY    := $(VENV)/bin/python
# The stamp, not the directory, is the target. `python3 -m venv` creates the
# directory before `pip install` runs, so a failed install left something
# newer than pyproject.toml and make considered it done forever after: every
# later `make check` skipped the recipe and failed with `No module named
# ruff`, which does not resemble its cause. Written only on success.
STAMP := $(VENV)/.installed

help:
	@echo "make check    format --check, lint, test"
	@echo "make format   ruff format ."
	@echo "make lint     ruff check ."
	@echo "make test     pytest"
	@echo "make fetch    pull a fresh snapshot from the UDM into cache/"
	@echo "make render   render diagrams from cache/ into out/"
	@echo "make map      fetch + render everything (svg, pdf, drawio)"
	@echo "make tree     render in the readable (non-UniFi) layout"
	@echo "make offline  render with builtin icons, no network access"
	@echo "make demo     render the shipped demo dataset (no controller needed)"
	@echo "make demo-dark       the same dataset in the dark theme"
	@echo "make demo-overrides  the same dataset with the example overrides applied"
	@echo "make demo-images     regenerate the demo PNGs committed under docs/images/"
	@echo "make docs           regenerate the flag reference and man page from the parser"
	@echo "make dark     render from cache in the dark theme"
	@echo "make build    build a wheel and sdist into dist/"
	@echo "make clean    remove out/, dist/ and caches"

$(STAMP): pyproject.toml
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -e ".[dev]"
	@touch $(STAMP)

check: $(STAMP)
	$(PY) -m ruff format --check .
	$(PY) -m ruff check .
	$(PY) -m pytest -q

docs: $(STAMP)
	$(PY) scripts/generate_cli_docs.py
	$(PY) scripts/generate_manpage.py

format: $(STAMP)
	$(PY) -m ruff format .

lint: $(STAMP)
	$(PY) -m ruff check .

test: $(STAMP)
	$(PY) -m pytest -q

fetch: $(STAMP)
	$(VENV)/bin/unifi-map fetch

render: $(STAMP)
	$(VENV)/bin/unifi-map render --per-network -f svg pdf drawio

map: $(STAMP)
	$(VENV)/bin/unifi-map all --per-network -f svg pdf drawio

tree: $(STAMP)
	$(VENV)/bin/unifi-map render --layout tree -f svg pdf drawio

offline: $(STAMP)
	$(VENV)/bin/unifi-map render --icons builtin --offline -f svg pdf drawio

dark: $(STAMP)
	$(VENV)/bin/unifi-map render --theme dark --per-network -f svg pdf drawio html

demo: $(STAMP)
	$(VENV)/bin/unifi-map --cache-dir examples/demo --out-dir examples/demo \
		render --per-network -f svg pdf drawio html --name demo --title "Demo network"

demo-dark: $(STAMP)
	$(VENV)/bin/unifi-map --cache-dir examples/demo --out-dir examples/demo \
		render --theme dark --per-network -f svg pdf drawio html --name demo-dark \
		--title "Demo network"

demo-overrides: $(STAMP)
	$(VENV)/bin/unifi-map --cache-dir examples/demo --out-dir examples/demo \
		render --overrides examples/demo/overrides.toml -f svg --name demo-overrides \
		--title "Demo network, with overrides"

# The demo images committed under docs/images/. Not run by `make check`: they
# are large binaries, and a rendering change should update them deliberately
# rather than dirty the tree on every build. See the script for what is
# generated and why the crop is computed rather than hard-coded.
demo-images: $(STAMP)
	$(VENV)/bin/python scripts/make_demo_images.py

demo-snapshot:
	python3 scripts/make_demo_snapshot.py

# A wheel and an sdist in dist/, installable anywhere with pip. Not a published
# package: whether this project should ever own a name on PyPI is a separate and
# still-open question, because publishing is the part that cannot be undone.
#
# dist/ is emptied first. Left alone it accumulates every version ever built,
# and `pip install dist/*.whl` then resolves to whichever sorts last rather than
# the one just built.
build: $(STAMP)
	$(VENV)/bin/pip install -q build
	rm -rf dist
	$(PY) -m build
	@echo
	@echo "Install it with:  pip install dist/*.whl"

clean:
	rm -rf out dist build .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
