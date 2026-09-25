# 0068 — Russian agent scenarios and quantity evaluation

## Objective

Make Russian the tested natural-language surface for the newly implemented quantity/lifecycle/Undo behavior and extend provider-neutral scenarios without adding multilingual machinery.

## Prompt behavior

The default system prompt and relevant clarification/mutation guidance are designed for Russian.

The agent must:

- distinguish known facts from inference;
- prefer performing a safe quantity action before asking a nonessential quantity clarification;
- mention when precision degrades to unknown or an estimate conflicts with the operation;
- not infer removed state from arithmetic alone;
- use remove only from user removal intent;
- use generic remove reasons from explicit text or unambiguous context;
- use immediate Undo only for the previous eligible mutation turn;
- preserve existing target ambiguity safety.

## Required Russian scenarios

Add provider-neutral cases covering at least:

- exact partial move;
- approximate partial move;
- unknown source with exact separated amount;
- "часть/немного" where action proceeds and precision becomes unknown;
- approximate underflow/inconsistent estimate with user notice;
- partial remove such as giving away some units;
- whole "снять с учёта";
- restore;
- duplicate/equivalent lots distinguished by stable evidence;
- copied cable-length comment becoming suspicious after split: operation succeeds, then agent surfaces the ambiguity;
- immediate "отмени" after a supported action;
- Undo unavailable after an intervening read-only turn;
- target ambiguity still clarifies before write.

## Language scope

Do not add:

- language detection;
- transliteration;
- Ukrainian/Russian equivalence;
- English/Russian semantic mapping;
- cross-language embeddings.

Latin technical names/model identifiers remain ordinary data.

Existing historical non-Russian fixtures may remain when they test lower-level contracts; new product behavior is evaluated in Russian.

## Focused verification

    .venv/bin/python -m pytest -q tests/test_prompts.py tests/test_scenario_eval.py tests/test_eval_checks.py -k "quantity or partial or removed or restore or undo or russian"
    just scenario-check
    just scenario-eval
    just compile
    git diff --check
