# Flower SuperExec image for Armadillo clientapp containers.
# Contains common machine-learning libraries (CPU only), so approved apps run
# without installing packages, and this package, so apps can import its helpers.
# TensorFlow is not included: it has no packages for this image's Python 3.13.
# The base image and all packages are pinned exactly, so every data station runs
# the same versions. Build from the repository root:
#   docker build -f docker/superexec-armadillo.Dockerfile -t <image> .
FROM flwr/superexec:1.32.1@sha256:a851d265cef72e634bfb83bffdde806e6a876f30894ea765862e6536cbac3cef

# PyTorch, CPU version, from the PyTorch package index.
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      torch==2.6.0 torchvision==0.21.0

# Other machine-learning and data libraries, from PyPI.
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
