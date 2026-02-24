FROM flwr/superexec:1.23.0

# Install git (needed for molgenis-auth dependency)
USER root
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
USER app

WORKDIR /app

# Install molgenis_flwr_armadillo from local source
COPY src/ /molgenis_flwr_armadillo/src/
COPY pyproject.toml /molgenis_flwr_armadillo/
COPY README.md /molgenis_flwr_armadillo/
RUN python -m pip install -U --no-cache-dir /molgenis_flwr_armadillo

# Install the Flower app
COPY examples/quickstart-pytorch/pyproject.toml .
COPY examples/quickstart-pytorch/pytorchexample/ ./pytorchexample/

RUN sed -i 's/.*flwr\[simulation\].*//' pyproject.toml \
   && sed -i 's/.*molgenis-flwr-armadillo.*//' pyproject.toml \
   && python -m pip install -U --no-cache-dir .

ENTRYPOINT [ "flower-superexec" ]
