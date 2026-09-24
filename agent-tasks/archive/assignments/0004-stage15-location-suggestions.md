# Assignment 0004: Stage 15 evidence-based location suggestions

Protocol: `agent-tasks/common/v3.md`

Repository: `buzlet/ah-there-it-is`
Branch: `feat/stage15-location-suggestions`

## Objective

Add a deterministic, read-only location-suggestion layer for items whose current location is unknown. Suggestions must remain explicitly distinct from known inventory state: they are evidence derived from existing history and related items, never a replacement for `Item.current_location_id` and never an authorization to mutate inventory.

## Required implementation

1. Add a typed service-layer location-suggestion result.
   - Keep the implementation provider/model independent.
   - Do not put inference logic in prompts or in the tool handler.
   - Do not persist suggested/probable locations and do not add a schema migration in this stage.
   - If an item has a non-null current location, return no inferred suggestions. The stored current location remains the authoritative fact.
   - If the item current location is null, return at most the requested limit of deterministic candidates with stable location IDs, full paths, and explicit evidence/reason metadata. Do not emit invented probability/confidence percentages.

2. Use only existing inventory evidence.
   - **Own history:** derive a `last_known` candidate from the most recent item event that contains usable location evidence. For an `item_taken` event, its `from_location_id` is the last known stored location; otherwise prefer a non-null `to_location_id`, then a non-null `from_location_id`.
   - **Related current items:** consider other items that currently have a known location and are related by the same non-null category and/or at least one shared tag.
   - Aggregate related-item evidence by location using unique supporting item IDs. Preserve whether support came from `same_category`, `shared_tag`, or both.
   - If own-history and related-item evidence point to the same location, return one candidate with combined evidence.
   - Do not use name similarity, free-form LLM reasoning, embeddings, provider calls, or external data.

3. Make ranking deterministic and explainable.
   - A `last_known` location always ranks ahead of candidates supported only by related items.
   - Among candidates without `last_known`, rank by supporting related-item count descending.
   - For equal support, prefer a candidate supported by both category and tag evidence over one evidence type.
   - Finish ties by stable location ID ascending.
   - Repeated calls over unchanged database state must produce the same ordered result.

4. Expose the capability as a read-only agent tool, e.g. `suggest_item_locations`.
   - Require the item ID to be unambiguously resolved before the tool may run.
   - The tool must not mutate the item, create history events, or write suggestion state.
   - Suggested location IDs may become **seen** for follow-up read inspection, but must never become **resolved** merely because they were suggested.
   - A later mutation still requires the normal location search/resolution path.
   - Tool output/descriptions must make the uncertainty explicit so a model cannot legitimately present a suggestion as the stored current location.

5. Preserve the existing prompt/version contract.
   - `prompts/inventory-v1.txt` already requires known data to be distinguished from inference. Do not rewrite that versioned prompt in this stage.
   - Do not add provider/model-specific prompt branches or live-model requirements.

6. Extend deterministic application coverage.
   - Add focused unit/service tests for: known-current-location -> no suggestions; own-history `last_known`; related-item category evidence; shared-tag evidence; combined evidence; aggregation/ranking/tie stability; no evidence -> empty result.
   - Add tool authorization coverage proving an unresolved item cannot request suggestions and a suggested location cannot directly authorize a mutation.
   - Extend the provider-independent corpus/scenario suite with representative user behavior for an item whose location becomes unknown and is then queried.
   - Include at least one scenario that uses `last_known` evidence and one that exercises related-item evidence.
   - Preserve independent persisted-state/event postconditions. Suggestion/read turns must not create mutations or history events beyond any explicit preceding user mutation in the scenario.

7. Keep storage/recovery contracts unchanged.
   - Do not change `inventory-portable-v1`.
   - Do not change SQLite backup/restore semantics.
   - Because suggestions are derived and non-persistent, portable import must reconstruct the underlying evidence through existing inventory/history data rather than serialize suggestion state.

8. Update user-facing documentation only as needed to describe the known-vs-suggested location behavior and its evidence sources.
   - Do not mark Stage 15 complete.
   - Do not invent Stage 16. Stage transition remains the orchestrator's responsibility after the merged assignment is reviewed.

## Constraints

- No database migration or new persistent suggestion table.
- No embeddings.
- No provider/model/network changes or live-provider verification.
- No voice/Telegram/images/QR/MCP/PWA/cloud/multi-user work.
- No dependency, runtime, or GitHub Actions version changes.
- No unrelated refactoring.
- Keep the application pipeline deterministic and provider independent.

## Verification and delivery

Follow `agent-tasks/common/v3.md` for the full implementation + verification + PR/CI correction + merge cycle.

In focused verification, include the new suggestion service/tool/scenario tests. Then run the complete protocol-v3 canonical verification set on the final implementation before PR delivery and again as required after any correction.

Create `agent-tasks/reviews/0004-r1.md`, merge only after required CI is green, synchronize local `main`, and return the compact protocol-v3 summary.
