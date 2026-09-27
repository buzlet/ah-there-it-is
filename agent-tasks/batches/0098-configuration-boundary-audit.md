# Batch: 0098-configuration-boundary-audit

Full local required: `false`

## Objective

Perform a focused configuration-boundary research/audit for issue #101.

The goal is to define what counts as configuration in this project, identify
hard-coded values that should or should not move into configuration, and make
the model future-compatible with possible per-user preferences without
implementing multi-user support now.

This is primarily a design/audit batch. Do not perform broad configuration
refactoring.

## Product context

Current product scope remains one logical user.

However, future versions may support multiple users or externally managed user
profiles. Therefore the audit must identify which values are:

- global deployment/operator settings;
- secrets;
- product defaults / UX tuning;
- future per-user preferences;
- domain invariants;
- protocol/API constants;
- internal implementation constants.

The audit must also identify who may change each configurable value:

- developer only;
- operator/admin;
- user through external tooling;
- user through application/chat preference.

## Required classification criteria

Define practical tests for deciding whether a hard-coded value belongs in
configuration.

At minimum distinguish:

1. **Domain invariants**
   - correctness/safety rules;
   - never user-configurable;
   - examples: transaction atomicity, idempotency guarantees, safety gates,
     valid state transitions.

2. **Protocol/API constants**
   - externally fixed mechanics and wire/API spellings;
   - normally remain next to implementation.

3. **Deployment/operator configuration**
   - values that vary by host, environment, provider, installation or runtime.

4. **Secrets/credentials**
   - tokens, passwords, OAuth/private-key material;
   - separate from ordinary non-secret configuration.

5. **Product defaults / UX tuning**
   - stable defaults that may legitimately be changed globally without changing
     correctness semantics.

6. **Future user preferences**
   - behavior that may legitimately differ per logical user later.

7. **Internal implementation constants**
   - private mechanics that should remain code unless there is a concrete
     operational/product need to expose them.

For every category explain both inclusion and exclusion criteria.

## Audit scope

Inspect at minimum:

- application settings/config parsing;
- `.env.example`;
- deployment/runtime configuration and documentation;
- Telegram client/poller/progress behavior;
- Telegram UX timing/tuning candidates from issue #100;
- provider/model/reasoning settings;
- web bind/network settings;
- pagination and result limits;
- retry/backoff/timeout values;
- paths and storage locations;
- user-visible UX timing/presentation constants;
- feature switches;
- hard-coded user-facing policy;
- test constants that may actually represent production policy.

Do not mechanically classify every literal. Focus on values with plausible
operator, product-policy or user-preference meaning.

## Candidate inventory

For each candidate record:

- file/symbol;
- current value;
- classification;
- rationale;
- keep hard-coded vs externalize;
- secret sensitivity;
- globally configurable now?;
- future per-user override?;
- allowed changer/owner;
- proposed key/name if applicable;
- code default vs required explicit value;
- migration/backward-compatibility impact.

## Configuration layering research

Do not assume one physical configuration file.

Evaluate and recommend a layering model such as:

1. committed application defaults;
2. non-secret deployment configuration;
3. separate secret material;
4. optional operator overrides;
5. future persisted user-preference/profile layer.

Define precedence explicitly. A candidate direction is:

`product default -> deployment/operator override -> future user override`

while domain invariants remain non-overrideable and secrets stay in a separate
channel.

Assess whether the current environment-variable approach should remain
authoritative for deployment configuration, whether a file-backed non-secret
configuration layer is useful, and what representation would be appropriate
for future user preferences.

Optimize for:

- simple single-host operation now;
- explicit production behavior;
- safe secret handling;
- reproducibility;
- testability;
- minimal operator burden;
- future per-user customization without redesigning core correctness;
- no hidden model-specific behavior.

## Deliverable

Add a concise design/audit document under `agent-tasks/designs/` containing:

1. classification criteria;
2. repository candidate inventory;
3. recommended configuration layering and precedence;
4. concrete values to externalize now;
5. concrete values that should deliberately remain code;
6. candidates for future per-user preferences;
7. naming conventions;
8. migration/backward-compatibility considerations;
9. grouped follow-up implementation issues/batches.

Update issue #101 with the final document reference and summary if the executor
workflow permits GitHub issue comments/updates.

## Verification

This is a documentation/research batch.

At minimum:

- verify every cited file/symbol/value against the exact branch contents;
- run `git diff --check`;
- if any executable code is changed, add appropriate targeted tests and run
  `make compile`.

Exact-head CI remains repository-wide authority if a PR is opened.

## Non-goals

- implementing multi-user support;
- introducing a user-profile schema;
- moving all constants into configuration;
- broad configuration refactoring;
- secret migration;
- changing production runtime values;
- issue #100 Telegram UX implementation;
- issues #97–#99 Russian semantics implementation.

## Handoff

Stop at `READY FOR REVIEW`.

Report:

- exact implementation SHA;
- design/audit document path;
- major classification conclusions;
- values recommended for immediate externalization;
- values recommended for future per-user override;
- values deliberately kept in code;
- verification performed;
- PR/CI status if applicable.


## Executor notifications

Use the selected U24 executor notification protocol. Every milestone notification
must include the wrapper-provided 5-hour and weekly remaining percentages plus
relative time remaining until each reset. Notifications are best-effort
operational UX and do not change acceptance criteria.


## Independent review emphasis

The independent reviewer must reconstruct the configuration-boundary decision
from the issued task and repository evidence rather than relying on the
implementer's conclusions.

Review adversarially for:

- values incorrectly classified as user preference when they are correctness or
  safety invariants;
- values incorrectly frozen in code despite legitimate per-deployment or future
  per-user variability;
- secret/non-secret layering mistakes;
- precedence that would allow a user preference to override a domain invariant;
- recommendations that accidentally require multi-user implementation now;
- missing inventory of hard-coded Telegram/provider/runtime tuning values;
- containment-plausibility policy from #97 being omitted or treated as an
  irreversible invariant;
- migration recommendations that are more complex than the current single-host
  product needs.

If findings require correction, append the narrowest documentation/design
corrections to the same branch, verify them, and finish with
`REVIEW COMPLETE — CORRECTED`. Otherwise finish with
`REVIEW COMPLETE — CLEAN`.
