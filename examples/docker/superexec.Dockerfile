FROM flwr/superexec:1.27.0

WORKDIR /app

# Copy packages from build context (molgenis-python-auth copied in by build script)
COPY molgenis-python-auth /tmp/molgenis-python-auth
COPY . /tmp/molgenis-flwr-armadillo
COPY examples/quickstart-pytorch/pyproject.toml .

USER root
RUN pip install --no-cache-dir /tmp/molgenis-python-auth \
   && sed -i 's/.*molgenis-auth.*/    "molgenis-auth",/' /tmp/molgenis-flwr-armadillo/pyproject.toml \
   && pip install --no-cache-dir /tmp/molgenis-flwr-armadillo \
   && sed -i 's/.*flwr\[simulation\].*//' pyproject.toml \
   && sed -i 's/.*molgenis-flwr-armadillo.*//' pyproject.toml \
   && pip install --no-cache-dir . \
   && rm -rf /tmp/molgenis-python-auth /tmp/molgenis-flwr-armadillo
# Flower 1.27.0 (PR #6700) suppresses ServerApp stdout/stderr via subprocess.DEVNULL,
# making debugging impossible. Remove the DEVNULL override so logs remain visible.
RUN sed -i '/stdout.*DEVNULL/d; /stderr.*DEVNULL/d' \
    /python/venv/lib/python3.13/site-packages/flwr/supercore/superexec/plugin/serverapp_exec_plugin.py \
    && rm -f /python/venv/lib/python3.13/site-packages/flwr/supercore/superexec/plugin/__pycache__/serverapp_exec_plugin.cpython-313.pyc
USER app

ENTRYPOINT [ "flower-superexec" ]
