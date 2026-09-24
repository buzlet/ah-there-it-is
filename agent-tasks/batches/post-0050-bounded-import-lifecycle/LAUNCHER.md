# Launcher — bounded portable import and lifecycle alignment 0051–0060

```text
Работай как implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol:
- `agent-tasks/common/v8.md`

Execution:
- host_profile: `u24-bash`
- execution_channel: `direct-shell`
- execution_user: `rdu01`
- workdir: `/home/rdu01/projects/bounded-import-lifecycle-0051-0060`

Работай только как rdu01 и только в этом checkout.
Не используй sudo/su.
Если каталога нет — создай свежий canonical checkout именно там.

Для независимых shell calls используй:
`cd /home/rdu01/projects/bounded-import-lifecycle-0051-0060 || exit 1`

Не выполняй shell PATH export и не activate venv.
Direct Python: `.venv/bin/python ...`
Just: обычный `just ...`; Justfile сам использует абсолютный repo-local .venv path.

Batch control:
- branch: `queue/post-0050-bounded-import-lifecycle`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0050-bounded-import-lifecycle/manifest.md`

Start prerequisite:
- `origin/main == c6609139e16384e3de48f9b403a426dcf2fa9e9c`

Implementation branch:
- `feat/bounded-import-lifecycle-0051-0060`

Прочитай только:
- AGENTS.md;
- agent-tasks/common/v8.md;
- exact manifest + 0051–0060 specs из immutable control SHA;
- relevant source/tests.

Не читай archive рекурсивно.

Создай один batch seed и выполни строго:
0051 → 0052 → 0053 → 0054 → 0055 → 0056 → 0057 → 0058 → 0059 → 0060.

После каждой задачи:
- task self-review;
- только declared focused checks;
- just compile;
- git diff --check;
- checkpoint commit.

Не запускай full repository suite между задачами.

Этот batch имеет `full_local_required: true`, потому что меняет storage/import и verification tooling.
Полный v8 regression запускается один раз после 0060 и final integration checks.

Не входи в quantity/physical-instance, split/merge, undo/purge, retention, automated backup policy, auth/multi-user, provider/model, schema/index migrations, dependency additions, Python 3.13+ verification или CI workflow changes.

После всех checkpoint'ов:
- cumulative seed..HEAD self-review;
- один pre-PR batch review по актуальному v8;
- final integration;
- один full-local v8 gate;
- один PR;
- authoritative exact-head CI;
- narrow correction loop только при необходимости;
- merge commit после green exact head;
- clean main sync;
- seed ancestry proof;
- post-merge completion report.

После merge верни compact batch report.
```
