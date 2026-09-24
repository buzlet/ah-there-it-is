# Launcher — operational read scalability v3

```text
Работай как implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol:
- `agent-tasks/common/v8.md`

Execution:
- host_profile: `u24-bash`
- execution_channel: `direct-shell`
- execution_user: `rdu01`
- workdir: `/home/rdu01/projects/operational-read-scalability-0035-0039-v3`

Среда уже работает как `rdu01`.

Не используй sudo или su.
Не переключай пользователя.
Не работай в другом checkout.

Если `/home/rdu01/projects/operational-read-scalability-0035-0039-v3` ещё не существует, создай свежий checkout canonical repository именно там.

Перед любой mutation проверь:
- `id -un == rdu01`
- `HOME == /home/rdu01`
- `pwd == /home/rdu01/projects/operational-read-scalability-0035-0039-v3`
- Git toplevel == `/home/rdu01/projects/operational-read-scalability-0035-0039-v3`

Batch control:
- branch: `queue/post-0034-operational-read-scalability-v3`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0034-operational-read-scalability-v3/manifest.md`

Start prerequisite:
- `origin/main == 1937abe8bc2096175112927af8f2d67e97e516c5`

Implementation branch:
- `feat/operational-read-scalability-v3`

Прочитай только:
- `AGENTS.md`;
- `agent-tasks/common/v8.md`;
- exact manifest/task specs из указанного control SHA;
- нужные source/tests.

Не читай рекурсивно `agent-tasks/archive/`.

Создай один batch seed и выполни:
`0035 → 0036 → 0037 → 0038 → 0039`.

После каждой задачи:
- task self-review;
- только focused checks из manifest;
- `just compile`;
- `git diff --check`;
- checkpoint commit.

Не запускай полный repository test suite между задачами.

`full_local_required: false`.
Перед PR выполни только final integration checks из manifest.

После failed mutation сначала inspect current Git/file state; не повторяй тот же patch transport вслепую.

После всех задач:
- cumulative self-review;
- один batch review;
- один PR;
- один authoritative full CI;
- merge commit после green exact head;
- clean main sync;
- seed ancestry proof.

После merge верни compact batch report.
```
