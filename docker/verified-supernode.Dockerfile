FROM flwr/supernode:1.27.0

USER root
COPY . /tmp/molgenis-flwr-armadillo
RUN apk add --no-cache git \
    && pip install --no-cache-dir /tmp/molgenis-flwr-armadillo \
    && apk del git \
    && rm -rf /tmp/molgenis-flwr-armadillo
USER app

ENTRYPOINT ["python", "-m", "molgenis_flwr_armadillo.supernode_verify"]
