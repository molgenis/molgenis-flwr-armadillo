FROM flwr/superlink:1.27.0

# Fix: the stock SuperLink discards verifications from directly submitted FABs.
# This one-line patch preserves them so supernode --trusted-entities works.
USER root
RUN sed -i 's/            fab_file = request.fab.content/            fab_file = request.fab.content\n            verification_dict = dict(request.fab.verifications)/' \
    /python/venv/lib/python3.13/site-packages/flwr/superlink/servicer/control/control_servicer.py \
    && rm -f /python/venv/lib/python3.13/site-packages/flwr/superlink/servicer/control/__pycache__/control_servicer.cpython-313.pyc
USER app