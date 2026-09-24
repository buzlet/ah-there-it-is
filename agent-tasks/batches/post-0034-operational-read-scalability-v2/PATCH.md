# Patch launcher: operational read scalability 0035–0039 v2

Work only in:

`/home/rdu1/Projects/operational-read-scalability-0035-0039-v2`

Execution user:

`rdu1`

Do not use sudo or switch users.

Control branch:

`queue/post-0034-operational-read-scalability-v2`

Immutable control SHA is supplied externally with this patch.

Manifest:

`agent-tasks/batches/post-0034-operational-read-scalability-v2/manifest.md`

Expected start main:

`eac461ab1ec1dafc81c058df7a15a23e77ff7096`

Implementation branch:

`feat/operational-read-scalability-v2`

Read only:
- `AGENTS.md`;
- `agent-tasks/common/v8.md`;
- exact manifest/task specs at the supplied control SHA;
- relevant source/tests.

Do not recursively read the archive.

Before mutation verify you are `rdu1`, HOME is `/home/rdu1`, and Git toplevel is exactly `/home/rdu1/Projects/operational-read-scalability-0035-0039-v2`.

If the checkout does not exist, create it fresh at that exact path from the canonical repository remote.

Create one batch seed and execute 0035 → 0039 in order.

After every task run only the manifest-declared focused checks plus compile/diff-check, then commit a checkpoint.

`full_local_required: false`: do not run the full repository suite locally.

After all tasks run only the final integration checks from the manifest, create one batch review and one PR, use one authoritative final CI, then merge with a merge commit.

After a failed mutation, inspect current Git/file state before constructing a new edit. Do not repeatedly replay the same failed patch transport.

Return one compact batch report after merge.
