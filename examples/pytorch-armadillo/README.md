# quickstart-pytorch-armadillo

Federated CIFAR-10 training with Flower and PyTorch, loading data from
[MOLGENIS Armadillo](https://github.com/molgenis/molgenis-service-armadillo)
via its `/flower/push-data` endpoint.

The app runs in both Flower runtimes without code changes:

- **Simulation**: data is partitioned on the fly with
  [Flower Datasets](https://flower.ai/docs/datasets/). The default federation
  expects 2 virtual SuperNodes.
- **Deployment**: each ClientApp loads its node's data from the local
  Armadillo server. The SuperExec container is started by Armadillo, which
  injects `ARMADILLO_URL` and `ARMADILLO_CONTAINER_NAME`. The researcher
  authenticates with each Armadillo node
  (`armadillo-flwr-authenticate`, from
  [molgenis-flwr-armadillo](https://github.com/molgenis/molgenis-flwr-armadillo))
  and submits the run with `armadillo-flwr-run`, which injects one OIDC token
  per node as `token-<sanitized-url>` run-config keys.

## Simulation

```bash
pip install -e .
flwr run .
```

## Deployment

1. Upload the CIFAR-10 partitions to each Armadillo node as
   `data/cifar10_train.pt` and `data/cifar10_test.pt` in the project named by
   the `project` run-config key (default `test-flower`). Use
   `pytorchexample/split_data.py` to generate per-node partitions.
2. Authenticate with each node: `armadillo-flwr-authenticate`.
3. Submit the run: `armadillo-flwr-run . --federation local-deployment --stream`.

Data pushed into the container is read into memory and deleted immediately;
see the molgenis-flwr-armadillo documentation for details.
