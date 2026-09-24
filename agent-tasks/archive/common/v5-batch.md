# Autonomous batch implementation protocol v5

This protocol is a thin execution wrapper around `agent-tasks/common/v4.md`. It allows one implementation+verification agent to execute multiple **pre-issued** assignments without an orchestrator handoff between merges.

The batch agent gains execution autonomy only. It does not gain product or architecture authority.

## Authority

The user launches the batch with:

- a batch control branch;
- an immutable `control_sha`;
- a manifest path.

The exact files at `control_sha` are the issued batch contract. Do not amend, rewrite, replace, or reinterpret them.

The batch agent may execute only tasks listed in that manifest and only in the declared order/dependency policy.

## Environment

All repository, terminal, test and GitHub work must use Remote Commander on U24, device `u24-gpt`.

If U24 is unavailable, stop with a blocker. Do not move to another execution environment.

## Batch start

1. `git fetch origin`.
2. Verify the provided control SHA exists and the named control branch still points to it.
3. Read this protocol, the manifest and the exact task specs from `control_sha` using Git, not a mutable working copy.
4. Switch to `main`, pull with `--ff-only`, confirm clean.
5. Verify every manifest prerequisite.
6. Record `batch_start_main_sha=$(git rev-parse HEAD)`.
7. From this point, an unexpected external advance of `origin/main` is a stop condition.

The control branch may have been created before the prerequisite implementation merged. Therefore its parent does not define the batch start main. The prerequisite checks do.

## Just-in-time assignment seed

Future task branches are intentionally **not** pre-seeded. After the preceding task merges:

1. sync clean `main`;
2. confirm `origin/main` is exactly the merge result expected from the preceding batch task;
3. create the task branch named in the manifest from that `main`;
4. copy the exact task spec bytes from `control_sha` to the manifest's assignment destination;
5. for the first batch task only, also copy this v5 protocol and the immutable manifest into their declared repository destinations;
6. create exactly one ordinary seed commit;
7. record `seed_sha` and `base_main_sha`;
8. verify the seed parent equals current `origin/main`;
9. do not open a PR for the seed;
10. immediately continue with the per-assignment lifecycle.

For v5 just-in-time seeds, the immutable batch manifest is the pre-issued strategy/status artifact. The seed therefore does not need speculative AGENTS/HANDOFF/README edits merely to repeat the assignment. Factual project documentation is updated only when the task is actually delivered.

The seed and copied assignment are immutable under the same rules as v4: no amend, rebase, squash, reset-away or force-push rewrite.

## Per-assignment lifecycle

After creating the seed, follow protocol v4 for:

- scope discipline;
- implementation;
- self-review;
- focused verification;
- canonical verification;
- factual completion docs;
- review record;
- one implementation PR;
- CI correction loop;
- merge commit;
- clean main synchronization.

The v5 wrapper changes only who is authorized to create the next pre-issued seed.

Each review record must additionally record:

- batch ID;
- batch `control_sha`;
- previous batch merge SHA, or batch-start main for the first task.

## Continue rule

After a successful task merge:

1. sync `main`;
2. verify the task seed is an ancestor of `main`;
3. record the merge SHA;
4. fetch origin once;
5. if `origin/main` differs from that merge SHA before the next seed is created, stop for unexpected main advance;
6. otherwise create and execute the next listed task.

Do not return to chat between successful tasks.

## Stop conditions

Stop the entire batch and return a compact blocker report if any of these occur:

- a task exposes a materially unresolved product/architecture decision not already settled by its spec;
- required behavior conflicts with a repository invariant;
- U24 becomes unavailable;
- a required local verification failure remains unexplained after normal diagnosis;
- current-task CI remains blocked after the permitted correction loop;
- an external/unlisted commit advances `main` after batch start;
- credentials, provider account action or other manual authorization becomes required;
- a dependent preceding task does not merge successfully;
- the immutable control files cannot be read or no longer match the provided control SHA.

Do not skip a failed task and do not substitute another task.

## No roadmap authority

The batch agent must not:

- add or delete tasks;
- reorder tasks;
- expand task scope;
- create Stage 26 location-truth policy;
- make new lifecycle/product semantics not resolved by a spec;
- continue beyond the final manifest task.

## CI and merge

Every code task keeps its own PR, full applicable CI and merge commit. Batch mode does not combine these tasks into one integration PR.

Ordinary seed pushes should not trigger full CI under the repository workflow model.

## Final report

After the final task merges, return one compact batch report containing:

- batch ID and control SHA;
- batch-start main SHA;
- for every assignment: branch, seed SHA, final implementation SHA, PR, merge SHA, review path, focused/canonical/CI result, correction counts;
- any deviations;
- final clean main SHA.

If stopped, return the completed-task summary plus the exact blocking task and condition.
