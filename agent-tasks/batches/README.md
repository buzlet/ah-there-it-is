# Issued tasks

Under v9, each new task/batch is one Markdown file committed to `main`:

`agent-tasks/batches/<batch-id>.md`

The commit containing the finalized file is the immutable **issuance SHA**.

This file defines only work and verification. It does not select or describe an
execution environment.

The orchestrator supplies the executor separately:

`Executor: agent-tasks/executors/<profile>.md`

No control branch, copied assignment files, launcher or seed commit is required.

Completed task files may be archived later by the orchestrator; archival is not
part of implementer/reviewer lifecycle.
