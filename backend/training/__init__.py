"""Training pipeline: exporter (Mongo → JSONL), storage (R2 + local fallback),
Modal dispatch, webhook receiver, eval runner.

Phase A (built): storage, exporter, wired dataset export.
Phase B (pending creds): modal_client, train.py, webhooks, eval_runner.
"""
