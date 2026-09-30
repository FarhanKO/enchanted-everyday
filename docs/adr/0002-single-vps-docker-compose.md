# ADR 0002: One VPS running Docker Compose, not a PaaS

**Status:** accepted, 2026-09-30

## Context

The workload is a daily batch job (a few minutes of FFmpeg), an always-on bot and a small database.
Candidates: Render/Railway-style PaaS, serverless functions plus managed Postgres, or one VPS.

## Decision

A Hostinger KVM 2 (2 vCPU, 8 GB RAM) running one Docker Compose stack. The same Compose file runs locally.

## Why

- **Cost.** About $9-15 a month for everything. A PaaS bills the worker, bot and database separately, and video
  rendering needs more RAM and time than free tiers allow.
- **FFmpeg and long jobs.** Serverless time and memory limits don't suit rendering.
- **Same stack everywhere.** Compose locally, in CI and in production. The host stays swappable: moving is
  `provision_vps.sh`, restore the nightly dump, `docker compose up`.
- **Small attack surface.** SSH is the only open port. The bot uses long polling, and the Prefect UI is reached
  through an SSH tunnel.

## Costs

We own OS patching (unattended-upgrades), backups (nightly pg_dump to R2) and uptime (dead-man's switch).
A single box is a single point of failure. The three-video buffer and a rebuild time under an hour cover that.
