# 0086 — Lifecycle, Undo, media and quantity integration hardening

## Objective

Adversarially verify the combined quantity/split/remove/restore/media/immediate-Undo semantics now that all subsystems coexist.

## Required work

Cover combinations, not only isolated operations:

- exact / approximate / unknown quantity;
- partial move / take / remove split;
- removed → restore;
- source Item media retained while split child receives none;
- media attach/update/detach in the same user turn as other supported mutations where legal;
- multi-receipt Undo;
- stale post-state before Undo;
- failure during compensation;
- creation Undo;
- split Undo without Item merge;
- media detach/Undo without external-byte deletion.

Required invariants:

- source/remainder stable ID remains stable;
- split child never inherits source media automatically;
- Undo is one-level compensation, not history rewrite or redo;
- all compensation for one turn is atomic;
- stale state fails closed with no partial compensation;
- removed Items retain their meaningful quantity/media evidence;
- no operation infers removal from quantity zero.

Fix only reproduced defects.

## Focused verification

    .venv/bin/python -m pytest -q       tests/test_quantity_semantics.py       tests/test_quantity_split.py       tests/test_removed_lifecycle.py       tests/test_undo.py       tests/test_item_media.py       tests/test_media_telegram_integration.py       tests/test_atomic_turn_receipts.py
    make compile
    git diff --check
