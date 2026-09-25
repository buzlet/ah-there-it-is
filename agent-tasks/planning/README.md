# Planning

This directory contains future implementation plans that are not yet immutable
issued controls.

Current reserved core-MVP lanes after merged batch 0061-0070:

- `post-0070-media-telegram-core/` — tasks 0071–0080 for Item photo references and the single-user Telegram text adapter;
- `post-0070-model-evaluation/` — tasks 0081–0083 for provider/model benchmark campaign and promotion-report tooling.

The two lanes are intentionally designed to start from the same reconciled main
SHA and to be merge-order independent.

Before issuing either lane:

1. inspect the actual current main;
2. update exact focused checks and file ownership;
3. assign immutable control SHA, expected start-main SHA, execution channel and workdir;
4. seed the active `agent-tasks/batches/` and `agent-tasks/assignments/` paths under v8.

Planning material is not executable authority until converted into an immutable
issued batch.
