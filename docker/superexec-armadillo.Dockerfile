# Batteries-included Flower SuperExec runtime image for Armadillo apps.
# One image covering the common ML frameworks, so a data station pulls a single
# runtime and can run any app using them without a live per-run dependency
# install (run the superexec WITHOUT --allow-runtime-dependency-installation and
# Flower executes the app in this image's venv, /python/venv).
#
# All CPU-only (no CUDA). Also bakes the molgenis-flwr-armadillo package
# (--no-deps) so apps import the helpers instead of vendoring them.
#
# TensorFlow is intentionally NOT included: it has no wheels for the base
# image's Python 3.13. To support TF, build a separate image on a py3.12 base,
# or revisit once TF ships py3.13 wheels.
#
# Everything is pinned exactly — base image by digest, packages by version — so
# every data station runs an identical numeric stack (federated determinism).
#
# Build from the repo root:
#   docker build -f docker/superexec-armadillo.Dockerfile -t <image> .
FROM flwr/superexec:1.32.1@sha256:a851d265cef72e634bfb83bffdde806e6a876f30894ea765862e6536cbac3cef

# Deep learning — CPU-only PyTorch from the PyTorch CPU index.
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      torch==2.6.0 torchvision==0.21.0

# Classic / tabular ML, from PyPI.
RUN pip install --no-cache-dir \
      numpy==2.5.3 \
      scipy==1.18.1 \
      pandas==3.0.5 \
      scikit-learn==1.9.0 \
      xgboost==3.4.1

# The molgenis-flwr-armadillo package, without its CLI-only dependencies
# (molgenis-auth, rich): nothing imported inside the container needs them.
COPY --chown=app pyproject.toml README.md /tmp/pkg/
COPY --chown=app src /tmp/pkg/src
RUN pip install --no-cache-dir --no-deps /tmp/pkg && rm -rf /tmp/pkg

# Armadillo sets this entrypoint explicitly as well; it is here for running the image by hand.
ENTRYPOINT ["armadillo-flwr-superexec"]
