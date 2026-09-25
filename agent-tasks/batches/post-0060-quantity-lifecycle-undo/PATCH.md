# Patch intent

Implement the accepted homogeneous-lot quantity model, generic removed/restore lifecycle, portable-v3 and immediate one-level compensating Undo.

Authoritative semantics:
- agent-tasks/designs/quantity-physical-instance-decision.md
- agent-tasks/designs/undo-correction-decision.md
- agent-tasks/designs/product-scope-decisions.md

This batch intentionally excludes merge, hard delete, multi-user/auth, transports, images, voice, QR/barcodes, multilingual/search expansion, backup policy, trace purge and provider/model promotion.

Control branch:
queue/post-0060-quantity-lifecycle-undo

Control SHA:
<CONTROL_SHA>
