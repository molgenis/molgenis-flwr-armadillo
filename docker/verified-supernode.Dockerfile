FROM flwr/supernode:1.27.0

USER root
COPY molgenis-python-auth /tmp/molgenis-python-auth
COPY . /tmp/molgenis-flwr-armadillo
RUN pip install --no-cache-dir --no-deps /tmp/molgenis-python-auth \
    && pip install --no-cache-dir --no-deps /tmp/molgenis-flwr-armadillo \
    && rm -rf /tmp/molgenis-python-auth /tmp/molgenis-flwr-armadillo
USER app

ENTRYPOINT ["python", "-m", "molgenis_flwr_armadillo.supernode_verify"]
