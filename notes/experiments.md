# Experiments log

This file records experiments performed while developing or operating the project,
including unsuccessful attempts and negative results.

The purpose is reproducibility and institutional memory, not polished documentation.

## Recording rules

For each meaningful experiment, record:

- date and short title;
- status: planned | running | completed | inconclusive | abandoned;
- question / hypothesis;
- exact environment or relevant commit/SHA;
- setup and important inputs;
- commands or procedure sufficient to reproduce it;
- observed result;
- interpretation / conclusion;
- limitations or uncertainty;
- follow-up action, if any.

Do not record secrets, production tokens, private runtime data, or credentials.

Negative results are valuable. Do not delete an experiment merely because it failed.
If a later experiment supersedes it, link the newer entry and mark the older one as
superseded.

Experiments in this branch do not become implementation requirements automatically.
A result that should affect the product or process must be promoted through the normal
design/planning/task flow.

## Entry template

### YYYY-MM-DD — Short experiment title

Status: completed

Question:
What are we trying to learn?

Context:
Relevant repository SHA, branch, host/executor, versions, and constraints.

Procedure:
1. ...
2. ...

Observed result:
- ...

Conclusion:
- ...

Limitations:
- ...

Follow-up:
- ...

---

_No experiment entries yet._
