.PHONY: help check format lint test map fetch render tree sane offline dark demo \
        demo-overrides demo-images demo-snapshot docs clean

VENV := .venv
PY   := $(VENV)/bin/python

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
	@echo "make demo-overrides  the same dataset with the example overrides applied"
	@echo "make demo-images     regenerate the demo PNGs committed under docs/images/"
	@echo "make docs           regenerate the README flag reference from the parser"
	@echo "make dark     render from cache in the dark theme"
	@echo "make clean    remove out/ and caches"

$(VENV): pyproject.toml
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -e ".[dev]"
	@touch $(VENV)

check: $(VENV)
	$(PY) -m ruff format --check .
	$(PY) -m ruff check .
	$(PY) -m pytest -q

docs: $(VENV)
	$(PY) scripts/generate_cli_docs.py

format: $(VENV)
	$(PY) -m ruff format .

lint: $(VENV)
	$(PY) -m ruff check .

test: $(VENV)
	$(PY) -m pytest -q

fetch: $(VENV)
	$(VENV)/bin/unifi-map fetch

render: $(VENV)
	$(VENV)/bin/unifi-map render --per-network -f svg pdf drawio

map: $(VENV)
	$(VENV)/bin/unifi-map all --per-network -f svg pdf drawio

tree: $(VENV)
	$(VENV)/bin/unifi-map render --layout tree -f svg pdf drawio

sane: tree
	@echo "make sane is deprecated and goes away in 0.5.0; use make tree."

offline: $(VENV)
	$(VENV)/bin/unifi-map render --icons builtin --offline -f svg pdf drawio

dark: $(VENV)
	$(VENV)/bin/unifi-map render --theme dark --per-network -f svg pdf drawio

demo: $(VENV)
	$(VENV)/bin/unifi-map --cache-dir examples/demo --out-dir out/demo \
		render --per-network -f svg pdf drawio --name demo --title "Demo network"

demo-overrides: $(VENV)
	$(VENV)/bin/unifi-map --cache-dir examples/demo --out-dir out/demo \
		render --overrides examples/demo/overrides.toml -f svg --name demo-overrides \
		--title "Demo network, with overrides"

# The demo images committed under docs/images/. Not run by `make check`: they
# are large binaries, and a rendering change should update them deliberately
# rather than dirty the tree on every build. See the script for what is
# generated and why the crop is computed rather than hard-coded.
demo-images: $(VENV)
	$(VENV)/bin/python scripts/make_demo_images.py

demo-snapshot:
	python3 scripts/make_demo_snapshot.py

clean:
	rm -rf out .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
