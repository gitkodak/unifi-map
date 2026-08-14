# Built by ClusterFuzzLite's own GitHub Actions (build_fuzzers), not by this
# repo's ci.yml -- oss-fuzz-base is Google's image and is not something we
# maintain or pin further here; ClusterFuzzLite's own actions choose the tag.
#
# Runs as root, flagged by static analysis and left as-is: oss-fuzz-base's own
# build tooling (compile_python_fuzzer and friends) assumes it, this build
# never runs as a long-lived service, and the image is never published
# anywhere -- it exists for the minutes this job runs and is discarded after.
FROM gcr.io/oss-fuzz-base/base-builder-python

# Not the latest (3.1.0): oss-fuzz-base's Python/platform combination has no
# prebuilt wheel for it, and --only-binary=:all: refuses to fall back to a
# source build. 3.0.0 is confirmed available for this image.
RUN pip3 install --only-binary=:all: atheris==3.0.0

# Named explicitly rather than `COPY . $SRC/unifi-map`: an allowlist can only
# ever copy what it names, where a blocklist (the repo root .dockerignore,
# kept anyway as a second layer) has to be remembered every time something
# new needs excluding. A contributor's local cache/ in particular can hold a
# real network's MAC/hostname/IP inventory -- see CLAUDE.md's data-hygiene
# section -- and has no business anywhere near this build.
COPY pyproject.toml LICENSE unifi-map.1 $SRC/unifi-map/
COPY src $SRC/unifi-map/src
COPY requirements $SRC/unifi-map/requirements
COPY .clusterfuzzlite $SRC/unifi-map/.clusterfuzzlite
COPY .clusterfuzzlite/build.sh $SRC/

WORKDIR $SRC/unifi-map
