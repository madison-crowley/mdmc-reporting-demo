# MDMC Reporting Platform

This repository contains the public core of MDMC's config-driven reporting platform plus a single demo deployment in `configs/demo.yaml`.

The platform is designed to be deployed per client:

- client-specific behavior lives in YAML config, not in core code
- BigQuery is the warehouse
- the public demo uses open and synthetic data only
- the top-level Python source package is `mdmc_platform`

Use `scripts/run_pipeline.py` as the entrypoint. A fuller README is intentionally deferred to a later task.
