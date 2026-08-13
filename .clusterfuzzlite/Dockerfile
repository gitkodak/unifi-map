# Built by ClusterFuzzLite's own GitHub Actions (build_fuzzers), not by this
# repo's ci.yml -- oss-fuzz-base is Google's image and is not something we
# maintain or pin further here; ClusterFuzzLite's own actions choose the tag.
FROM gcr.io/oss-fuzz-base/base-builder-python

RUN pip3 install atheris

COPY . $SRC/unifi-map
COPY .clusterfuzzlite/build.sh $SRC/

WORKDIR $SRC/unifi-map
