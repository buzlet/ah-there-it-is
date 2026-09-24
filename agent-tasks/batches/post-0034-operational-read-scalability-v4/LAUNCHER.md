# Launcher — operational read scalability v4

```text
Работай как implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol:
- `agent-tasks/common/v8.md`

Execution:
- host_profile: `u24-bash`
- execution_channel: `direct-shell`
- execution_user: `rdu01`
- workdir: `/home/rdu01/projects/operational-read-scalability-0035-0039-v4`

Среда уже работает как `rdu01`.
Не используй sudo/su и не переключай пользователя.
Работай только в указанном checkout.

Если workdir отсутствует, создай свежий checkout canonical repository именно там.

Выполни полный execution preflight только один раз при старте batch:
- user == rdu01
- HOME == /home/rdu01
- cd в exact workdir
- Git toplevel == exact workdir
- project venv/Python valid

После успешного startup preflight НЕ повторяй user/HOME/Git-toplevel проверки перед каждой mutation.

Каждый последующий independent shell command начинай только с:
`cd /home/rdu01/projects/operational-read-scalability-0035-0039-v4 || exit 1`
и восстановления repo-local venv PATH.

Полный preflight повторяй только после реального session reset/reconnect либо если есть фактический признак потери cwd/repository context.

Batch control:
- branch: `queue/post-0034-operational-read-scalability-v4`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0034-operational-read-scalability-v4/manifest.md`

Start prerequisite:
- `origin/main == 471fc313ec532371e860f1a72ba38544b5a9376e`

Implementation branch:
- `feat/operational-read-scalability-v4`

Прочитай только AGENTS.md, v8, exact manifest/task specs и нужные source/tests.
Не читай archive рекурсивно.

Создай один batch seed и выполни 0035 → 0036 → 0037 → 0038 → 0039.

После каждого task:
- task self-review;
- только focused checks из manifest;
- just compile;
- git diff --check;
- checkpoint commit.

Не запускай полный repository test suite между задачами.

full_local_required=false.
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
