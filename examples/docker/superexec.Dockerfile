FROM flwr/superexec:1.27.0

WORKDIR /app

# Copy the molgenis-flwr-armadillo package (build context = repo root)
COPY . /tmp/molgenis-flwr-armadillo
# Copy the app's pyproject.toml
COPY examples/quickstart-pytorch/pyproject.toml .

USER root
RUN apt-get update && apt-get install -y --no-install-recommends git \
   && pip install --no-cache-dir /tmp/molgenis-flwr-armadillo \
   && sed -i 's/.*flwr\[simulation\].*//' pyproject.toml \
   && sed -i 's/.*molgenis-flwr-armadillo.*//' pyproject.toml \
   && pip install --no-cache-dir . \
   && apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* /tmp/molgenis-flwr-armadillo
USER app

ENTRYPOINT [ "flower-superexec" ]
