# Issued batches

Under v9, each new batch is one Markdown file committed to `main`:

`agent-tasks/batches/<batch-id>.md`

The commit containing the finalized file is the immutable **issuance SHA**.

A batch defines work/verification and links exactly one executor profile under
`agent-tasks/executors/`.

Do not duplicate executor details inside the batch.

No control branch, copied assignment files or seed commit is required.

Completed batch files may be archived later by the orchestrator; archival is not
part of implementer/reviewer lifecycle.
