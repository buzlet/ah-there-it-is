# Launcher

```text
Работай как implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol:
- `agent-tasks/common/v8.md`

Execution:
- host_profile: `u24-bash`
- execution_channel: `direct-shell`
- execution_user: `rdu1`
- workdir: `/home/rdu1/Projects/operational-read-scalability-0035-0039-v2`

Весь batch выполняй только как `rdu1` и только в каталоге:

`/home/rdu1/Projects/operational-read-scalability-0035-0039-v2`

Не используй sudo/su и не переключайся на gpt.
Не работай в другом checkout.

Если каталога ещё нет, создай свежий checkout canonical repository именно там.

Перед любой mutation проверь:
- `id -un == rdu1`
- `HOME == /home/rdu1`
- `pwd == /home/rdu1/Projects/operational-read-scalability-0035-0039-v2`
- Git toplevel == `/home/rdu1/Projects/operational-read-scalability-0035-0039-v2`

Batch control:
- branch: `queue/post-0034-operational-read-scalability-v2`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0034-operational-read-scalability-v2/manifest.md`

Start prerequisite:
- `origin/main == eac461ab1ec1dafc81c058df7a15a23e77ff7096`

Implementation branch:
- `feat/operational-read-scalability-v2`

Выполни 0035 → 0036 → 0037 → 0038 → 0039 по v8.

После каждого task:
- self-review текущего diff;
- только focused checks из manifest;
- `just compile`;
- `git diff --check`;
- checkpoint commit.

Не запускай полный repository test suite между задачами.

`full_local_required: false`.
Перед PR выполни только final integration checks из manifest.

Если mutation command упал, не повторяй его вслепую:
- сначала `git status --short`;
- `git diff`;
- `git diff --cached`;
- inspect target;
- затем новая операция из текущего состояния.
После двух неудач одного edit strategy смени стратегию.

После всех задач:
- один cumulative self-review;
- один batch review;
- один PR;
- один authoritative final CI;
- merge commit после green exact head;
- sync clean main и prove seed ancestry.

После merge верни compact batch report.
```
