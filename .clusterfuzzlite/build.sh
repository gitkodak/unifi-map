#!/bin/bash -eu
# Run by ClusterFuzzLite's build_fuzzers action inside the Dockerfile's image.
# $SRC and $OUT are set by the oss-fuzz-base image, not by us.

cd "$SRC/unifi-map"
pip3 install .

cp .clusterfuzzlite/fuzz_support_archive.py "$SRC/"
compile_python_fuzzer "$SRC/fuzz_support_archive.py"

# See make_seed_corpus.py for why a seed matters here: a blind mutation
# engine essentially never produces a valid gzip header on its own.
python3 .clusterfuzzlite/make_seed_corpus.py "$OUT/fuzz_support_archive_seed_corpus.zip"
