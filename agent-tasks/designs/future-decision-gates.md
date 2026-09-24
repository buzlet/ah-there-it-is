# Future decision gates

Status: planning map while autonomous batch 0019–0023 is running.  
This document identifies places where implementation should stop for an explicit product/architecture decision rather than allowing an agent to infer policy.

## Executive map

The near-term path is:

```text
0019–0023 batch
    |
    +--> Gate A: retrieval evidence + CI coverage baseline
    |
    +--> Gate B: close remaining Stage 26 semantics
              |
              +--> Stage 26 implementation batch
                       |
                       +--> Gate C: duplicates / quantity / physical instances
                       +--> Gate D: correction / undo / retirement visibility
                       +--> Gate E: privacy retention / operational backup policy
                       +--> Gate F: remote access / multi-user / sync only if wanted
```

Not every future feature needs a pause. The important rule is: pause when the next change alters **meaning**, **data compatibility**, **identity**, **ownership**, or **security boundary**.

---

## Gate A — immediately after the current 0019–0023 batch

### A1. Retrieval robustness results

Assignment 0023 deliberately measures unsupported RU/UK/EN query classes without changing SearchService.

This is a mandatory evidence gate.

Possible outcomes:

- current intended normalization is sufficient → do nothing;
- candidate starvation violates an existing invariant → issue a narrowly scoped retrieval bugfix;
- real failures are mostly typo/edit-distance → decide whether a fuzzy fallback is justified;
- real failures are mostly cross-script RU/UK/EN transliteration → decide whether transliteration is justified;
- real failures are mostly morphology/inflection → decide whether aliases, lightweight morphology, or another approach is justified;
- no measured need for embeddings → keep embeddings deferred.

### Default recommendation

Do not choose a search technology in advance.

Prefer the smallest mechanism that fixes a measured failure class:

1. normalization/aliases;
2. narrowly bounded fuzzy fallback if necessary;
3. transliteration/morphology only when corpus evidence supports it;
4. embeddings only if lexical methods demonstrably cannot satisfy real queries.

### Agent stop condition

If 0023 discovers a current documented retrieval invariant failing, the batch spec already requires a stop rather than an opportunistic search redesign.

---

### A2. CI coverage baseline

PR #42 adds branch coverage reporting only in CI and intentionally has no `fail-under` yet.

After one or more representative CI runs we need to decide:

- report-only indefinitely;
- establish a global minimum;
- establish "do not decrease" semantics;
- later introduce module-specific expectations.

### Default recommendation

For now merge report-only coverage.

After the baseline stabilizes, prefer a modest global floor plus review of meaningful uncovered code rather than chasing 100%.

Do not make the very first measured number a hard gate merely because it is available.

This is a quality-policy decision, not a blocker for Stage 26 implementation.

---

## Gate B — before Stage 26 implementation

The broad Stage 26 model is already approved:

`location_status = known | unknown | in_use | not_applicable`

and `sold` joins `ItemState`.

Four details still need explicit closure before an autonomous implementation agent should receive the stage.

### B1. Portable format evolution — mandatory

Current `inventory-portable-v1` is intentionally frozen, strict, and rejects extra fields.

`location_status` cannot be added to v1 honestly without changing the frozen contract.

Decision required:

- introduce `inventory-portable-v2`;
- retain v1 import compatibility;
- define how imported v1 Items derive `location_status`.

### Default recommendation

Adopt portable-v2.

- Export current databases as v2.
- Continue importing v1 and v2.
- v1 import mapping:
  - non-null location → `known`;
  - null + discarded → `not_applicable`;
  - other null → `unknown`.
- Never export new Stage 26 state as v1 because that would discard meaning.

Bootstrap-v1 can remain simpler if its semantics already map deterministically:
- location supplied → known;
- no location → unknown;
- terminal-state handling must obey the Stage 26 invariants.

This decision is effectively forced by the existing frozen-v1 policy.

---

### B2. Reactivating sold/discarded Items — mandatory

The current design says terminal Items cannot be moved/taken until restored to a non-terminal state, but it does not define the restore operation.

Questions:

- Is `sold` reversible?
- Is `discarded` reversible?
- If restored, what non-terminal ItemState should it receive?
- Does restoration require a known location, or may it return as unknown?

### Default recommendation

Allow explicit reactivation because data-entry corrections happen.

Do not automatically restore the previous state.

Use one explicit operation conceptually like:

`reactivate_item(item_id, state, location_status/location_id)`

with:
- caller must choose a non-terminal state;
- resulting location truth must be explicit (`known` with ID or `unknown`);
- `in_use` may be chosen only through the explicit take/in-use operation after reactivation;
- record an immutable reactivation/correction Event.

This avoids hidden guesses about what a sold/discarded object "used to be".

---

### B3. Visibility of terminal Items — mandatory

Once `sold` and `discarded` become truthful terminal states, decide whether they remain in ordinary search/catalog views.

### Default recommendation

**Search:** keep terminal Items searchable by default.

A personal memory system should be able to answer "what happened to X?" with "sold" or "discarded" instead of pretending the object never existed.

**Browser catalog:** default to active Items, with an explicit filter for terminal/all Items.

**Agent search result:** include terminal status clearly; mutation tools reject inappropriate storage operations.

This preserves memory while keeping daily catalog browsing uncluttered.

---

### B4. Naming: ItemState unknown vs location_status unknown — small but explicit

The system will have:

- `ItemState.UNKNOWN` = physical/condition state unknown;
- `location_status=unknown` = whereabouts unknown.

These are different and valid, but UI/API labels must not collapse them.

### Default recommendation

Keep the internal enum names.

In UI/API documentation label them explicitly:

- Item condition/state: Unknown
- Location status: Location unknown

Do not invent more opaque enum vocabulary merely to avoid the repeated English word.

---

## After Gate B: Stage 26 implementation can be autonomous

Once B1–B4 are fixed, Stage 26 can be issued as a substantial implementation batch covering:

1. schema + conservative migration;
2. domain invariants and explicit move/take/unknown/terminal/reactivation transitions;
3. agent tools and deterministic scenarios;
4. browser UI/filtering and suggestion eligibility;
5. doctor + portable-v2/bootstrap compatibility.

No further product decision should be needed inside that batch if the assignment encodes the choices above.

---

## Gate C — identical physical instances and quantity semantics

This was deliberately excluded from Stage 26.

The unresolved question is what one `Item` represents.

Examples:

- 5 identical batteries in one box;
- 2 identical chargers in different rooms;
- quantity 5, move only 2 elsewhere;
- same product but different serial number/condition.

### Decision required

Choose a tracking model:

1. every physical object is its own Item;
2. Item may represent a fungible quantity;
3. hybrid: quantity is allowed only for indistinguishable co-located units and splits create separate Item groups.

### Default recommendation

Hybrid model.

- Unique/individually distinguishable objects → separate Items.
- Truly interchangeable units stored together → one Item with quantity.
- Partial move/sale/disposal → split into a new Item/group with its own stable ID and explicit provenance Event linking the split.

Before implementing this, define identity, split/merge history, aliases/attributes copying, and portable semantics.

This is a mandatory pause before partial-quantity operations.

---

## Gate D — correction/undo and retirement/delete policy

### D1. Undo/correction semantics

Once Activity/history becomes user-visible, users will eventually ask to undo an accidental move/edit/state transition.

Decision:

- destructive rollback/history deletion;
- compensating correction event;
- operation-specific undo links.

### Default recommendation

Never rewrite existing history for ordinary correction.

Use a new compensating mutation/Event that references the corrected Event ID where useful.

Decide separately which operations get a one-click undo UX. The domain principle should remain append-only audit evidence.

This is a decision gate before adding generic Undo.

---

### D2. Hard delete / archive / retirement

Sold/discarded covers physical terminal states but does not answer whether records should disappear from normal use.

Decision areas:

- archive flag vs terminal state;
- search visibility;
- whether hard delete ever exists;
- what happens to Event.item_id and historical references;
- portable behavior.

### Default recommendation

No ordinary hard delete.

Use terminal state + catalog filtering first.

If a later privacy/purge requirement appears, design a separate explicit destructive purge with strong warnings and documented history consequences. Do not overload "discarded" to mean database deletion.

---

## Gate E — privacy retention and operational backup policy

These are independent of Stage 26 but become important once real personal data accumulates.

### E1. Agent trace retention

Assignment 0017 stopped new provider secrets from leaking into config, but run logs still intentionally contain:

- system prompt;
- model input context;
- tool traces/results;
- final output.

Decision required before long-term real use:

- retain forever;
- retain N days;
- manual purge only;
- keep summary/evaluation data after deleting raw traces.

### Default recommendation

Keep current local retention until real usage volume is known, then add an explicit operator-visible retention policy.

Do not silently auto-delete audit data without a user-facing policy.

---

### E2. Automated backup schedule / retention

Backup/restore/rehearsal primitives exist, but scheduling/retention does not.

Decision eventually needed:

- automatic backup frequency;
- number/age retained;
- storage destination;
- whether backups leave the machine;
- encryption if they do.

### Default recommendation

For local-first MVP: simple local rotating backups first, no cloud upload by default.

This is not an immediate blocker while development data remains disposable.

---

## Gate F — network/security/ownership boundary

Assignment 0022 only prevents accidental non-loopback exposure. It is deliberately not authentication.

A mandatory architecture pause occurs if the desired product changes from:

> one user, local machine, loopback

to any of:

- LAN access from phone/tablet;
- Internet exposure;
- household/multiple users;
- cloud sync;
- remotely hosted instance.

### F1. Remote access

Before recommending non-loopback as normal operation decide:

- trusted private network only;
- Tailscale/WireGuard/reverse proxy;
- application token;
- user/password sessions;
- TLS ownership.

### Default recommendation

For one user across personal devices, prefer a trusted private overlay/reverse proxy before inventing a full account subsystem.

Do not expose the unauthenticated application directly to the public Internet.

---

### F2. Multi-user / household semantics

This is much larger than authentication.

It changes:

- who owns an Item;
- whether Locations are shared;
- who currently has an `in_use` Item;
- actor attribution in Events;
- permissions;
- suggestions and search visibility.

Do not bolt user IDs onto the existing schema until the collaboration model is chosen.

---

## Gate G — input modalities and automation

These are optional later product decisions rather than near-term blockers.

### Voice

Relatively low domain risk if it remains a transcription frontend to the same text API.

Decision points:
- local vs cloud transcription;
- confirmation rules for mutations;
- retention of audio.

### Images

Requires choices about:
- blob/file storage;
- thumbnails;
- model/image provider;
- privacy;
- whether images are evidence or merely attachments.

### QR/barcodes

Requires deciding:
- whether labels encode stable internal Item IDs;
- whether a scan may directly resolve write authority;
- label lifecycle after split/merge/replacement.

### Telegram/other chat integrations

Requires authentication/linking and idempotency mapping from external message IDs.

These should each be separate stages after core inventory semantics stabilize.

---

## Gate H — model/provider quality policy

The application deliberately remains model-independent.

Eventually, real-model evaluation may force choices about:
- acceptable clarification rate;
- provider cost/latency/privacy;
- prompt version promotion;
- whether structured confirmation is needed for risky writes.

### Default recommendation

Keep provider choice outside domain architecture.

Use deterministic application safety as the hard guarantee and evaluate models as replaceable frontends.

Do not make a provider/model choice a prerequisite for completing the inventory product.

---

## Recommended stopping sequence

### No decision needed during current 0019–0022

Those assignments are already sufficiently specified.

### Possible stop at 0023

Only if measured retrieval exposes a current invariant failure.

### Required review after 0023

Review:
- retrieval observations;
- candidate-starvation result;
- first CI coverage baseline.

Then merge/update PR #42 as appropriate.

### Required decision before Stage 26 implementation

Close B1–B4:
1. portable-v2;
2. terminal reactivation;
3. terminal visibility;
4. naming/UI distinction.

### Next mandatory product pause after Stage 26

Duplicate/quantity semantics (Gate C).

### Later pauses only when features are actually requested

- undo/delete (Gate D);
- trace retention/backups (Gate E);
- remote/multi-user (Gate F);
- modalities/integrations (Gate G);
- model/provider promotion policy (Gate H).

## Process recommendation

For future autonomous work, encode each resolved gate into a design file before creating the next batch.

A batch may safely cross many implementation tasks, but it should never cross an unresolved decision gate.

This preserves the useful pattern established by v5: humans choose semantics once; agents execute them for hours without repeatedly asking permission.
