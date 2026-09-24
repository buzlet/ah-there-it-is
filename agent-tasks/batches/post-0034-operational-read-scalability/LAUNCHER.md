# Launcher: direct U24 from RDU1, execute as gpt

Use the immutable control SHA supplied for this batch.

```text
Работай как implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol:
- `agent-tasks/common/v8.md`

Execution:
- host_profile: `u24-bash`
- execution_channel: `direct-shell`
- initial_user: `RDU1`
- target_user: `gpt`
- repo_path: `/home/gpt/projects/ah-there-it-is`
- sudo_available: true

Среда уже прозрачно подключена к U24. SSH не настраивать и отдельный Codex process не запускать.

Ты изначально работаешь как OS user `RDU1`, но ВСЕ операции с проектом должны выполняться как `gpt`.

Для каждого независимого command batch используй non-interactive sudo, логически:

sudo -n -u gpt -H bash -lc '
  cd /home/gpt/projects/ah-there-it-is
  export PATH="$PWD/.venv/bin:$PATH"
  <commands>
'

До любых изменений проверь внутри gpt-shell:
- `id -un` == `gpt`
- `HOME` == `/home/gpt`
- `pwd` == `/home/gpt/projects/ah-there-it-is`
- Python находится в repo `.venv`.

Не выполняй Git, редактирование, Python, Just или тесты под RDU1.
Не меняй ownership репозитория.
Если sudo к gpt не работает non-interactively — stop condition.

Batch control:
- branch: `queue/post-0034-operational-read-scalability`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0034-operational-read-scalability/manifest.md`

Start prerequisite:
- `origin/main` == `d63acfee8b2636753a7869c746057e1283c46b79`

Создай одну implementation branch:
- `feat/operational-read-scalability`

Создай один immutable batch seed по manifest и выполни задачи строго:
- 0035
- 0036
- 0037
- 0038
- 0039

После каждой задачи:
- task self-review;
- только declared focused checks;
- `just compile`;
- `git diff --check`;
- checkpoint commit.

Не запускай полный repository test suite между задачами.

В manifest:
- `full_local_required: false`

Поэтому перед PR НЕ запускай локальный `just check` целиком. Выполни только final integration checks из manifest.

После всех задач:
- один cumulative self-review;
- один batch review;
- один PR;
- один authoritative full CI;
- bounded exact-head CI observation;
- narrow reproduction/focused checks при CI correction;
- merge commit только после green exact final head;
- sync clean main и prove seed ancestry.

Не переходи к quantity/physical-instance semantics и другим future decision gates.

После merge верни один compact batch report.
```
