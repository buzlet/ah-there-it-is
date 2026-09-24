# Assignment 0010: Stage 21 manual web administration parity

Protocol: `agent-tasks/common/v3.md`

Repository: `buzlet/ah-there-it-is`
Branch: `feat/stage21-manual-web-admin`

## Objective

Complete the local web UI as a deterministic manual fallback when an LLM is unavailable, wrong, or intentionally bypassed. A user must be able to create Items/Categories/Locations and correct the complete editable inventory facts through the browser while all validation, identity, history, FTS, and transaction behavior remains owned by the existing domain/service layer. This stage adds create/update only; deletion is deliberately out of scope.

## Required implementation

1. Add service-layer update operations for Category and Location.
   - Add explicit `InventoryService.update_category(...)` and `update_location(...)` (or one well-typed internal shared boundary with those public methods).
   - Support changing name, description, and parent while preserving the stable entity ID.
   - Distinguish omitted parent/description from an explicit null parent/description.
   - Validate the complete requested change before mutating the ORM object.
   - Reuse current normalized sibling identity rules; renaming/reparenting may not silently create a duplicate normalized sibling.
   - Reject self-parent and descendant-parent changes deterministically so category/location cycles cannot be introduced.
   - Parent changes must not rewrite Item stable references or create synthetic Item history events. Existing Item/Event location IDs keep referring to the same stable Location entity; rendered paths reflect the current tree.

2. Keep all browser mutations behind `InventoryService`.
   - Route handlers must not directly edit ORM inventory fields.
   - Manual Item creation uses `InventoryService.create_item` with `original_text="[manual web create]"`.
   - Manual Item correction uses `update_item` plus `move_item` where location changes, preserving the existing `[manual web edit]` provenance and normal `item_updated` / `item_moved` / `item_taken` semantics.
   - Manual Category/Location create/update uses the new/current InventoryService methods.
   - Do not add a generic repository/CRUD layer merely for the web UI.

3. Add strict request/response schemas for manual create/update.
   - Add Item create input for name, description, state, quantity, category_id, location_id, attributes, aliases, and tags.
   - Extend Item edit input to support attributes, aliases, and tags in addition to the existing fields.
   - Add Category and Location create/update inputs for name, description, and parent_id.
   - Keep `extra="forbid"`, existing length/range constraints, and current ItemState validation.
   - Unknown referenced IDs must produce the existing 404-style entity behavior; domain/identity/cycle conflicts must return clear 400 responses rather than raw tracebacks.
   - Do not expose `allow_duplicate` in the web API/UI. Existing intentional duplicate Items remain editable when name/category identity is unchanged, but manual creation/identity-changing edits retain normal duplicate prevention.

4. Add manual Item creation and full correction UI.
   - Add a clear `Add item` path from `/items` and a browser form for all Item create fields.
   - Item create/edit forms must expose aliases and tags as simple deterministic text inputs (one entry per line is preferred so commas remain valid name characters).
   - Expose attributes as a JSON-object textarea. Client-side parsing may provide immediate feedback, but the server schema/service remains authoritative. Reject non-object JSON cleanly.
   - Existing Item detail must allow clearing aliases, tags, attributes, category, location, and description intentionally.
   - Successful create redirects/navigates to the stable Item detail page; successful edit refreshes the authoritative server projection.
   - Do not add a frontend framework.

5. Add Category and Location create/update UI.
   - `/categories` and `/locations` must each provide an obvious create action/form.
   - Each listed node must have a stable edit path/page that exposes current name, description, and parent.
   - Parent selectors must display full paths and exclude the edited node itself and its descendants so the ordinary UI cannot propose a cycle; the service must still independently enforce cycle prevention.
   - Root is an explicit selectable parent state.
   - After rename/reparent, list/detail/item projections and search must show the new full paths while retaining stable IDs.
   - No delete buttons/endpoints in this stage.

6. Preserve search and derived-state behavior.
   - Creating/editing Item name/description/attributes/aliases/tags through the web must update FTS only through existing service/database trigger behavior.
   - Category/Location rename/reparent must remain visible to deterministic tree search/path rendering through current authoritative rows.
   - Do not persist rendered path strings or introduce a second path/index representation.

7. Preserve transactional and audit semantics.
   - Each HTTP mutation request must be atomic: validation failure leaves all authoritative/derived state unchanged.
   - One manual Item edit that changes ordinary fields and location may produce the existing separate `item_updated` and move/take events, but must not create duplicate/no-op events.
   - Category/Location create/update currently has no separate history model; do not invent one in this stage.
   - Do not alter AgentRunner transaction ownership or agent-tool authorization semantics.

8. Add focused API/UI/service coverage.
   - Category/Location rename, description clear/set, reparent-to-root, reparent-under-parent, duplicate-sibling rejection, self-parent rejection, descendant-cycle rejection, and rollback/no-partial-change behavior.
   - Manual creation of a fully populated Item and subsequent SearchService lookup by name, alias, tag, attribute, and description.
   - Full Item correction including clearing/replacing aliases/tags/attributes/category/location/description with expected history-event provenance/counts.
   - Existing intentional duplicate Item can receive non-identity edits; manual create or identity-changing edit into a duplicate remains rejected.
   - HTTP create/update routes return stable DTOs and appropriate 400/404/422 behavior.
   - HTML pages contain create/edit affordances and parent/full-path choices; target-scale inventory still uses the Stage 19 paged `/items` list rather than regressing to an unbounded item render.
   - If new static/template assets are added, include installed-wheel coverage proving they are packaged and served outside the checkout.

9. Update documentation only as needed.
   - Document that chat/LLM use is optional for inventory maintenance: the browser now provides deterministic manual create/correction for Items, Categories, and Locations.
   - State that delete remains deliberately unsupported in this stage.
   - Do not mark Stage 21 complete.
   - Do not invent Stage 22. Stage transition remains the orchestrator's responsibility after the merged assignment is reviewed.

## Constraints

- No delete endpoints/service methods and no cascade/deletion policy work.
- No database schema/Alembic migration.
- No new inventory/history model for Category/Location edits.
- No change to stable Item/Event IDs, portable-v1, bootstrap-v1, backup/restore, doctor/FTS-repair, or installed runtime/data-home semantics.
- No provider/model/network API changes, prompt changes, embeddings, or live-provider verification.
- No frontend framework, SPA rewrite, authentication, public deployment, or multi-user work.
- No systemd/service-manager, Docker/container, installer packaging, TLS, cloud, PWA, voice, Telegram, images, QR, or MCP work.
- No dependency/runtime/GitHub Actions upgrades and no unrelated refactoring.

## Verification and delivery

Follow `agent-tasks/common/v3.md` for the full implementation + self-review + focused verification + canonical verification + PR/CI correction + merge cycle.

Focused verification must include service-level tree update invariants, full manual Item create/edit/search/history behavior, API error/atomicity cases, browser page/form coverage, Stage 19 pagination non-regression, and installed-wheel asset smoke if applicable. Then run the complete protocol-v3 canonical verification set on the final implementation and after any task-related correction as required.

Create `agent-tasks/reviews/0010-r1.md`, merge only after required CI is green, synchronize local `main`, and return the compact protocol-v3 summary.
