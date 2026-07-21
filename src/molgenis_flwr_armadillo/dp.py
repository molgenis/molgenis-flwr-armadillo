"""Row-level (sample-level) differential privacy for Flower ClientApps.

DRAFT / preview. Generic DP-SGD via Opacus, designed so a **data owner** sets one
policy (epsilon, delta, clip quantile) — injected by Armadillo into the container
the same way ``ARMADILLO_URL`` is — and it works across model types without the
app author or researcher tuning per-model knobs.

Design
------
- The privacy budget (``epsilon``, ``delta``) and the clip target quantile are
  **policy**, set by the data owner via environment variables (see
  :func:`load_dp_policy`). The researcher's app cannot override them.
- The noise multiplier ``sigma`` is **derived** from (epsilon, delta, sampling
  rate, number of steps) — model-independent.
- The clipping norm ``C`` is **estimated per model** from a quantile of the
  observed per-sample gradient norms (see :func:`estimate_clip_norm`) — so it
  adapts to any architecture rather than being hand-tuned.

The app supplies only its model and a ``step_fn``; see :func:`dp_train`.

Requires the ``dp`` extra::

    pip install "molgenis-flwr-armadillo[dp]"

Note: ``epsilon`` is a POLICY choice, not a standard; ``delta`` should be <= 1/N.
See the disclosure-audit framework for references.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict

# Environment variables the Armadillo backend injects into the container — the
# same channel as ARMADILLO_URL. All optional; defaults are a starting policy.
ENV_EPSILON = "DP_EPSILON"
ENV_DELTA = "DP_DELTA"
ENV_CLIP_QUANTILE = "DP_CLIP_QUANTILE"

DEFAULT_EPSILON = 3.0
DEFAULT_DELTA = 1e-5
DEFAULT_CLIP_QUANTILE = 0.5

# A step function: given the (DP-wrapped) model and one batch, return the scalar
# loss. This is the ONLY app-specific code; it is responsible for moving the
# batch to the model's device.
StepFn = Callable[[Any, Any], Any]


@dataclass(frozen=True)
class DPPolicy:
    """Data-owner differential-privacy policy (model-independent)."""

    epsilon: float = DEFAULT_EPSILON
    delta: float = DEFAULT_DELTA
    clip_quantile: float = DEFAULT_CLIP_QUANTILE


def load_dp_policy() -> DPPolicy:
    """Read the DP policy from Armadillo-injected environment variables.

    The data owner sets ``DP_EPSILON`` / ``DP_DELTA`` / ``DP_CLIP_QUANTILE`` when
    launching the container; missing values fall back to the module defaults.
    """

    def _get_float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        return float(raw) if raw not in (None, "") else default

    return DPPolicy(
        epsilon=_get_float(ENV_EPSILON, DEFAULT_EPSILON),
        delta=_get_float(ENV_DELTA, DEFAULT_DELTA),
        clip_quantile=_get_float(ENV_CLIP_QUANTILE, DEFAULT_CLIP_QUANTILE),
    )


def make_dp_compatible(model):
    """Return a model Opacus can attach per-sample gradients to.

    Runs Opacus' ``ModuleValidator``: repairs what it can (notably
    BatchNorm -> GroupNorm) and **raises** for anything it cannot, so an
    incompatible model refuses to train rather than train without the promised
    protection. Call on BOTH server and client so the ``state_dict`` keys match.
    """
    from opacus.validators import ModuleValidator

    if ModuleValidator.validate(model, strict=False):
        model = ModuleValidator.fix(model)
        remaining = ModuleValidator.validate(model, strict=False)
        if remaining:
            raise RuntimeError(
                "Model cannot be made DP-compatible; refusing to train. "
                f"Unfixable modules: {remaining}"
            )
    return model


def estimate_clip_norm(
    model, loader, step_fn: StepFn, quantile: float, device: str = "cpu"
) -> float:
    """Estimate the clip norm C as a quantile of per-sample gradient norms.

    This is the model-adaptive part: rather than a fixed, model-specific C, set C
    to the given quantile (e.g. median) of the per-sample gradient norms observed
    on one batch, so it adapts to whatever architecture is passed in.
    """
    import torch
    from opacus import GradSampleModule

    gsm = GradSampleModule(model).to(device)
    gsm.train()
    gsm.zero_grad()
    step_fn(gsm, next(iter(loader))).backward()
    per_sample = torch.stack(
        [
            p.grad_sample.reshape(p.grad_sample.shape[0], -1).norm(dim=1)
            for p in gsm.parameters()
            if getattr(p, "grad_sample", None) is not None
        ]
    ).norm(dim=0)
    gsm.zero_grad()
    return float(torch.quantile(per_sample, quantile).item())


def dp_train(
    model,
    loader,
    step_fn: StepFn,
    policy: DPPolicy,
    q: float,
    T: int,
    *,
    local_epochs: int = 1,
    lr: float = 1e-3,
    device: str = "cpu",
) -> Dict[str, float]:
    """One federated round of sample-level DP-SGD via Opacus.

    Args:
        model: already passed through :func:`make_dp_compatible` and loaded with
            the server's weights.
        loader: the client's training ``DataLoader``.
        step_fn: ``step_fn(model, batch) -> scalar loss`` — the only app-specific
            code (its forward pass + loss; it moves the batch to ``device``).
        policy: the :class:`DPPolicy` from :func:`load_dp_policy`.
        q: sampling rate = batch_size / dataset_size.
        T: total number of federated rounds (from the server's per-round config),
            used to spread the privacy budget across rounds.

    Returns:
        Metrics including the achieved (local) epsilon this round.
    """
    import torch
    from opacus import PrivacyEngine
    from opacus.accountants.utils import get_noise_multiplier

    model.to(device)
    model.train()

    # C adapts to this model; sigma is derived from the budget over the whole run.
    clip_norm = estimate_clip_norm(model, loader, step_fn, policy.clip_quantile, device)
    steps_per_round = len(loader) * local_epochs
    sigma = get_noise_multiplier(
        target_epsilon=policy.epsilon,
        target_delta=policy.delta,
        sample_rate=q,
        steps=T * steps_per_round,
    )

    optimizer = torch.optim.SGD(model.parameters(), lr=lr)
    engine = PrivacyEngine()
    model, optimizer, loader = engine.make_private(
        module=model,
        optimizer=optimizer,
        data_loader=loader,
        noise_multiplier=sigma,
        max_grad_norm=clip_norm,
    )

    total_loss, n = 0.0, 0
    for _ in range(local_epochs):
        for batch in loader:
            optimizer.zero_grad()
            loss = step_fn(model, batch)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach())
            n += 1

    return {
        "train_loss": total_loss / max(1, n),
        "dp_epsilon_round": float(engine.get_epsilon(policy.delta)),
        "dp_clip_norm": clip_norm,
        "dp_noise_multiplier": float(sigma),
    }


# TODO (draft):
# - Cross-round accounting: sigma is sized for the whole run's total steps so the
#   TOTAL epsilon over T rounds ~= policy.epsilon, but the returned per-round
#   epsilon is local. A full implementation tracks the cumulative budget on the
#   Armadillo (data-owner) side and drops the node out when it is spent.
# - estimate_clip_norm uses a single batch; average over a few for stability.
# - Native adaptive clipping (Andrew et al. 2021) could replace the warmup
#   estimate once available in the Opacus/Flower path we use.
