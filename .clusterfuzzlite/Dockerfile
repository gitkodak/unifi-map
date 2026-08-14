# Built by ClusterFuzzLite's own GitHub Actions (build_fuzzers), not by this
# repo's ci.yml -- oss-fuzz-base is Google's image and is not something we
# maintain or pin further here; ClusterFuzzLite's own actions choose the tag.
#
# Runs as root, flagged by static analysis and left as-is: oss-fuzz-base's own
# build tooling (compile_python_fuzzer and friends) assumes it, this build
# never runs as a long-lived service, and the image is never published
# anywhere -- it exists for the minutes this job runs and is discarded after.
FROM gcr.io/oss-fuzz-base/base-builder-python

RUN pip3 install --only-binary=:all: atheris==3.1.0

# Scoped by the repo root .dockerignore: excludes .git, local caches and venvs
# so a contributor's own build never ships local state (a cache/ directory in
# particular can hold a real network inventory; see CLAUDE.md's data-hygiene
# section) into the image just because this copies recursively.
COPY . $SRC/unifi-map
COPY .clusterfuzzlite/build.sh $SRC/

WORKDIR $SRC/unifi-map
