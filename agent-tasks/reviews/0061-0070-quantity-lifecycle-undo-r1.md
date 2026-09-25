# Batch review: quantity lifecycle and immediate Undo 0061–0070

## Provenance

- Batch: `post-0060-quantity-lifecycle-undo-2026-09-25`
- Immutable control: `7e3f59c36c1085dc17af08e45624d0b6708faf34`
- Required start main: `fea00581b6f826534cb60d440d14f713da0d9849`
- Seed: `0b19e00` (active manifest plus byte-identical 0061–0070 assignments)
- Implementation branch: `feat/quantity-lifecycle-undo-0061-0070`

## Task checkpoints

| Task | Commit | Focused verification | Corrections |
|---|---|---|---:|
| 0061 | `084067e` | migration/wheel quantity, removed and legacy-state cases; migration-check; compile; diff-check | 0 |
| 0062 | `4b98128` | quantity semantic/domain cases; compile; diff-check | 0 |
| 0063 | `84d1bf2` | split/partial/move/take cases; compile; diff-check | 0 |
| 0064 | `7b4af54` | removed/restore/equivalent-lot lifecycle cases; compile; diff-check | 0 |
| 0065 | `45c967c` | agent/web/receipt quantity lifecycle cases; provider-contract; compile; diff-check | 0 |
| 0066 | `8a2de94` | portable-v3, frozen v1/v2, streaming and storage cases; compile; diff-check | 1 |
| 0067 | `0b61b90` | Undo/compensation/receipt/idempotency cases; compile; diff-check | 0 |
| 0068 | `e7b6140` | Russian prompt/scenario/eval cases; scenario-check/eval; compile; diff-check | 1 |
| 0069 | `eaddca2` | scale/atomicity/idempotency/crash/write-target cases; compile; diff-check | 0 |
| 0070 | `1ff00ab` | runtime/web/activity/CLI/doctor/storage/restore/migration/wheel cases; compile; diff-check | 1 |

## Cumulative self-review

The `0b19e00..HEAD` review covered schema invariants, semantic quantity changes,
atomic split behavior, generic removed/restore lifecycle, portable compatibility,
one-level compensating Undo, runtime projections and obsolete operation reachability.
It found legacy `InventoryService` sold/discard/reactivate shims and stale bootstrap
truth. Commit `3d63c1d` removed the first-class legacy operations and aligned bootstrap
and cross-suite runtime tests. Final-integration corrections in `ea17e02` moved old
generic quantity edits onto the semantic endpoint.

No scope expansion, dependency change, schema/index migration beyond the declared
0061 migration, provider/model promotion or CI workflow change was introduced.

## Final local verification

- Manifest final integration: green after narrow correction; all 18 declared test
  modules passed, provider-contract passed (23 tests), compile and diff-check passed.
- Full-local sequence was invoked exactly once. `migration-check`, `corpus-check`,
  `scenario-check`, `scenario-eval` (71/71) and `retrieval-eval` (86/86) passed.
- `just check` reported 539 passing and three stale test-fixture failures: two doctor
  corruption fixtures were blocked by the new database quantity check, and one live
  eval count expected the old fixture event total. Commit `b8c16e1` corrected only
  those fixtures; the three exact failing tests, compile and diff-check then passed.
  The full-local sequence was not repeated, per the one-run batch constraint; exact-head
  authoritative CI remains the repository-wide proof.

## Deviations and blockers

- No blockers.
- The one full-local run was not wholly green at its original head; its three failures
  were narrowly corrected and verified as described above rather than repeating the
  repository-wide local suite.
