# evals

The golden set that catches prompt regressions (started in Phase 1).

- `golden/` will hold 20 approved scripts as JSON (one file each), with the trend items they came from.
- `rubric.md` will score a script on hook strength, accuracy (every claim sourced), originality of take,
  length (110-150 spoken words) and caption quality.
- Every prompt change runs against the set before it ships; a drop in the average score blocks the change.

This depends on the niche decision (see `docs/decisions.md`), so it is empty for now.
