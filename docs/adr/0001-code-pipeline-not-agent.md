# ADR 0001: A Python pipeline with LLM calls, not an agent or n8n

**Status:** accepted, 2026-09-30

## Context

The system has to post every day with 95% reliability, under $30 a month, with every post traceable and
nothing published without approval. Three options:

1. **An autonomous agent** with tools to search, write, render and post
2. **A no-code workflow tool** (n8n, Make)
3. **A Python pipeline** of fixed stages, where the LLM is called inside a stage and only returns text

## Decision

Option 3.

## Why

- **Testable and reproducible.** Each stage is a function with typed input and output. It gets unit tests,
  schema tests on every LLM output, and integration tests against recorded API responses. An agent's
  path through its tools varies from run to run and is hard to regression-test.
- **Safe by construction.** The model has no tools, so prompt injection in scraped text can at worst
  produce a bad script, which the critic pass, the schema check and the human gate all catch. It can't post,
  spend or execute anything.
- **Cheap.** 3-4 bounded calls a day instead of an open-ended loop, plus a hard spend cap in code.
- **Real engineering.** Idempotent stages, migrations, CI and monitoring are better evidence for AI and MLOps
  roles than a workflow export.

## Costs

More code to write than n8n. The fixed stage order means new behaviour needs a code change, and that's intended.
