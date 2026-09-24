# Launcher — 0040 streaming evaluation export

```text
Работай как implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol:
- `agent-tasks/common/v8.md`

Execution:
- host_profile: `u24-bash`
- execution_channel: `direct-shell`
- execution_user: `rdu01`
- workdir: `/home/rdu01/projects/streaming-evaluation-export-0040`

Работай только как `rdu01` и только в указанном checkout.
Не используй sudo/su.
Если checkout отсутствует, создай свежий canonical checkout именно в этом каталоге.

Batch control:
- branch: `queue/post-0039-streaming-evaluation-export`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0039-streaming-evaluation-export/manifest.md`

Start prerequisite:
- `origin/main == 821910c1db1a65f06f3184321baa8683a1a87402`

Implementation branch:
- `feat/streaming-evaluation-export-0040`

Прочитай только:
- `AGENTS.md`;
- `agent-tasks/common/v8.md`;
- exact manifest + 0040 spec из immutable control SHA;
- relevant source/tests.

Не читай archive рекурсивно.

Важно для shell-команд:
- обычный prefix: только `cd /home/rdu01/projects/streaming-evaluation-export-0040 || exit 1`;
- НЕ выполняй `export PATH="$PWD/.venv/bin:$PATH"`;
- прямой Python: `.venv/bin/python ...`;
- Just recipes: обычный `just ...`.

Создай один immutable batch seed.

Выполни только assignment 0040.

Focused/final verification:
- `.venv/bin/python -m pytest -q tests/test_evaluation.py tests/test_evaluation_export.py`
- `just compile`
- `git diff --check`

`full_local_required: false`: локальный полный `just check` не запускать.

После реализации:
- task + cumulative self-review;
- один batch review;
- один PR;
- один authoritative full CI;
- merge commit только после green exact head;
- clean main sync;
- seed ancestry proof.

Не изменяй export schema, migrations, experiment replay, provider behavior или product semantics.

После merge верни compact batch report.
```
