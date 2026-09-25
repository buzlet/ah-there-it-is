# Launcher — 0061–0070 Remote Commander

Use the immutable control SHA issued externally for branch queue/post-0060-quantity-lifecycle-undo-rc.

Implementation branch:
feat/quantity-lifecycle-undo-0061-0070

Remote Commander:
- device: u24-gpt
- target user: gpt

Repository/workdir:
/home/gpt/projects/ah-there-it-is

Expected start main:
fea00581b6f826534cb60d440d14f713da0d9849

Read:
- AGENTS.md
- agent-tasks/common/v8.md
- this batch manifest and 0061–0070 exact specs from immutable control
- authoritative design docs explicitly referenced by the manifest
- relevant source/tests only

Do not read archive recursively.

Execution:
- Remote Commander only
- user gpt only
- no direct-shell
- no sudo/su
- all work only in /home/gpt/projects/ah-there-it-is
- direct Python: .venv/bin/python
- Just: plain just
- no venv activation or shell PATH export

Preflight:
- repository must be clean
- origin/main must equal fea00581b6f826534cb60d440d14f713da0d9849
- stop if the repository is occupied/dirty because of another active task

Execute strictly 0061 -> 0070 with one seed, one checkpoint per task, one final full-local gate, one PR and authoritative exact-head CI.
