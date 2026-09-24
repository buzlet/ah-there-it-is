# Launcher — storage/recovery hardening 0041–0050

```text
Работай как implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol:
- `agent-tasks/common/v8.md`

Execution:
- host_profile: `u24-bash`
- execution_channel: `direct-shell`
- execution_user: `rdu01`
- workdir: `/home/rdu01/projects/storage-recovery-hardening-0041-0050`

Работай только как rdu01 и только в этом checkout.
Не используй sudo/su.
Если каталога нет — создай свежий canonical checkout именно там.

Для независимых shell calls используй только:
`cd /home/rdu01/projects/storage-recovery-hardening-0041-0050 || exit 1`

Не выполняй `export PATH="$PWD/.venv/bin:$PATH"` и не activate venv.
Direct Python: `.venv/bin/python ...`
Just: обычный `just ...`.

Batch control:
- branch: `queue/post-0040-storage-recovery-hardening`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0040-storage-recovery-hardening/manifest.md`

Start prerequisite:
- `origin/main == 6e59e0285cf308d8329841ebf40d7162f49bcbec`

Implementation branch:
- `feat/storage-recovery-hardening-0041-0050`

Прочитай только:
- AGENTS.md;
- agent-tasks/common/v8.md;
- exact manifest + 0041–0050 specs из immutable control SHA;
- relevant source/tests.

Не читай archive рекурсивно.

Создай один batch seed и выполни строго:
0041 → 0042 → 0043 → 0044 → 0045 → 0046 → 0047 → 0048 → 0049 → 0050.

После каждой задачи:
- task self-review;
- только declared focused checks;
- just compile;
- git diff --check;
- checkpoint commit.

Не запускай full repository suite между задачами.

Этот batch имеет `full_local_required: true`, потому что затрагивает storage/restore/WAL.
Полный v8 regression запускается только один раз после 0050 и final integration checks.

Не заходи в quantity/physical-instance, undo/purge, retention, automated backup policy, multi-user/auth, provider/model или schema migrations.

После всех checkpoint'ов:
- cumulative self-review;
- один batch review;
- final integration;
- один full-local v8 gate;
- один PR;
- authoritative exact-head CI;
- merge commit после green head;
- clean main sync;
- seed ancestry proof.

После merge верни compact batch report.
```
