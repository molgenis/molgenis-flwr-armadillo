FROM flwr/supernode:1.23.0

USER root
RUN pip install --no-cache-dir molgenis-flwr-armadillo
USER app

ENTRYPOINT ["python", "-m", "molgenis_flwr_armadillo.supernode_verify"]
