# Launcher — 0061–0070

Use the immutable control SHA issued externally for branch queue/post-0060-quantity-lifecycle-undo.

Implementation branch:
feat/quantity-lifecycle-undo-0061-0070

Workdir:
/home/rdu01/projects/quantity-lifecycle-undo-0061-0070

Expected start main:
fea00581b6f826534cb60d440d14f713da0d9849

Read:
- AGENTS.md
- agent-tasks/common/v8.md
- this batch manifest and 0061–0070 exact specs from immutable control
- relevant source/tests only

Do not read archive recursively.

Execution:
- direct U24 shell
- user rdu01 only
- no sudo/su
- direct Python: .venv/bin/python
- Just: plain just
- no venv activation or shell PATH export

Execute strictly 0061 -> 0070 with one seed, one checkpoint per task, one final full-local gate, one PR and authoritative exact-head CI.
