# Built by ClusterFuzzLite's own GitHub Actions (build_fuzzers), not by this
# repo's ci.yml. Pinned to a digest rather than the mutable `latest` tag --
# same reasoning as every GitHub Action pin in this repo ("whoever controls
# the tag decides what runs") -- and tracked by Dependabot's docker ecosystem
# (dependabot.yml) so it still advances rather than going stale.
#
# Runs as root, flagged by static analysis and left as-is: oss-fuzz-base's own
# build tooling (compile_python_fuzzer and friends) assumes it, this build
# never runs as a long-lived service, and the image is never published
# anywhere -- it exists for the minutes this job runs and is discarded after.
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:6b2b3a7e4a2da50de47f94925cffbe34747e1aae4f33d7f07ba6c681dd648b23

# Hashed rather than a bare version pin (.clusterfuzzlite/requirements.in,
# regenerate with the same `pip-compile --generate-hashes` invocation
# requirements/ci.txt uses). Not folded into that shared lock: ci.yml never
# runs the fuzzer, and atheris has no reason to be installed into every CI
# job's environment just because this one build needs it. 3.0.0, not the
# newest release (3.1.0): oss-fuzz-base's Python/platform combination has no
# prebuilt wheel for 3.1.0, confirmed by actually running this build, not by
# reasoning about it in advance.
COPY .clusterfuzzlite/requirements.txt /tmp/atheris-requirements.txt
RUN pip3 install --require-hashes -r /tmp/atheris-requirements.txt

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
