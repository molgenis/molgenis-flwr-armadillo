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
USER app

ENTRYPOINT [ "flower-superexec" ]
