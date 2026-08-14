#!/bin/bash -eu
# Run by ClusterFuzzLite's build_fuzzers action inside the Dockerfile's image.
# $SRC and $OUT are set by the oss-fuzz-base image, not by us.

cd "$SRC/unifi-map"

# Same hashed lock ci.yml installs from (KAN-191), reused rather than
# maintaining a second one just for this build. It covers more than this
# build strictly needs (the dev and svg extras, plus pip-audit), which costs
# a slightly heavier image and nothing else, and keeps one lock file for
# Dependabot to track instead of two. --require-hashes rejects an editable
# install outright regardless of what else is on the command line, so the
# local package is a second, unhashed --no-deps install, exactly like
# ci.yml's own "Install" step.
pip3 install --only-binary=:all: --require-hashes -r requirements/ci.txt
pip3 install --no-deps --only-binary=:all: .

cp .clusterfuzzlite/fuzz_support_archive.py "$SRC/"
compile_python_fuzzer "$SRC/fuzz_support_archive.py"

# See make_seed_corpus.py for why a seed matters here: a blind mutation
# engine essentially never produces a valid gzip header on its own.
python3 .clusterfuzzlite/make_seed_corpus.py "$OUT/fuzz_support_archive_seed_corpus.zip"
