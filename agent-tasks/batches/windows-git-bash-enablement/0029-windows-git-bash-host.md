# Assignment 0029: Windows Git Bash implementation host enablement

Protocol for this enabling assignment: `agent-tasks/common/v5-batch.md` wrapping v4.

Branch: `feat/windows-git-bash-implementation-host`

## Objective

Make the repository's implementation+verification workflow portable between the existing U24 Bash host and native Windows 11 executed **exclusively through Git Bash**, while preserving the seeded-history, verification, PR/CI/merge and autonomous-batch guarantees established by protocols v4 and v5.

This assignment itself runs on U24. It prepares but does not falsely claim native-Windows validation.

## Architecture decision

Do not edit historical `agent-tasks/common/v4.md` or `v5-batch.md`.

Add a new:

`agent-tasks/common/v6.md`

that preserves the v4 single-assignment lifecycle and v5 batch mechanics, while replacing their hard-coded execution-environment clauses with an explicit launcher-selected execution profile.

## Required execution profiles

v6 supports exactly these initial profiles.

### `u24-bash`

Required launcher fields:

- `execution_profile: u24-bash`
- `device: u24-gpt`
- `repo_path: /home/gpt/projects/ah-there-it-is`

Behavior:

- all repository/file/terminal/test/GitHub work through Remote Commander on the supplied device;
- ordinary Bash environment;
- preserve current U24 workflow behavior.

### `windows-git-bash`

Required launcher fields:

- `execution_profile: windows-git-bash`
- `device: <explicit Remote Commander Windows device>`
- `repo_path: <absolute Git Bash path, e.g. /c/.../ah-there-it-is>`
- `git_bash_exe: <explicit native Windows path to bash.exe>`

Behavior:

- all repository, Git, test and verification commands run through **Git Bash**;
- do not use PowerShell or cmd for repository operations, tests, Git, file editing or lifecycle logic;
- the only allowed native-shell/bootstrap action is launching the supplied Git Bash executable itself when required by Remote Commander;
- once Bash is launched, remain in Bash for the complete command batch;
- prefer non-interactive `bash -lc`/equivalent command execution; do not depend on mintty or an interactive terminal;
- Python must be native Windows Python, not an MSYS Python runtime;
- launcher supplies the repository path in Git Bash form to avoid ad-hoc path guessing.

## Windows preflight required by v6

Before touching a seeded branch under `windows-git-bash`, verify from Git Bash:

- `MSYSTEM` is present and identifies a Git-for-Windows/MSYS environment;
- `uname` is consistent with that environment;
- `git --version` works;
- `bash --version` works;
- `python --version` is project-supported;
- native Python reports `os.name == "nt"`;
- `just --version` works;
- supplied `repo_path` exists and is the expected Git repository;
- worktree is clean before lifecycle start.

Set UTF-8-safe Python process behavior for agent command execution on Windows, for example through `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`, without changing persisted application semantics.

If preflight fails, stop. Do not silently fall back to PowerShell, cmd, WSL, U24 or another device.

## Host selection contract

The execution profile is supplied by the **user/orchestrator launcher**. The implementation agent must never infer or switch host profiles on its own.

v6 must show concise launcher examples for both profiles.

The selected profile remains fixed for the full assignment or full autonomous batch.

A batch may not switch from U24 to Windows or Windows to U24 between tasks unless a future protocol explicitly defines such behavior.

## Preserve lifecycle semantics

v6 must preserve, without weakening:

- immutable seed history;
- no amend/rebase/squash/force rewrite;
- exact branch ownership;
- focused verification;
- canonical verification;
- review records;
- one implementation PR per assignment;
- CI correction loop;
- merge commit;
- post-merge main synchronization;
- v5 just-in-time seed rules for pre-issued autonomous batches;
- external-main-advance stop behavior;
- no roadmap authority for implementation agents.

Where v4/v5 shell examples are POSIX-specific, v6 should express the invariant semantically and may provide Bash commands because both supported profiles use Bash.

## Make canonical repository verification Git-Bash/Windows compatible

### Just shell

Make the Justfile's shell contract explicit and compatible with:

- Bash on U24;
- Bash supplied by Git for Windows.

Do not introduce a PowerShell or cmd recipe fork.

Use capabilities supported by the repository's actual Just version; do not upgrade Just merely for this assignment.

### Temporary files

Remove canonical verification dependence on hard-coded `/tmp` application paths.

In particular address:

- migration-check temporary database;
- retrieval-eval default temporary report;
- any other canonical recipe changed/touched by this work that assumes `/tmp`.

Use Python/OS temporary-directory APIs (`tempfile`, `pathlib`) or an equivalent platform-neutral application helper.

The canonical suite must leave the branch/worktree clean on both profiles.

Do not merely substitute a Windows-specific hard-coded temp path.

### Environment variables

Inline Bash environment assignment is allowed because both profiles intentionally use Bash.

However, values passed to native Windows Python must not rely on ambiguous MSYS path conversion. Prefer generating native temporary paths/SQLite URLs inside Python helpers rather than embedding Git-Bash `/tmp` paths into database URLs.

## Refactor installed-wheel smoke for platform-neutral layout

`tests/test_wheel_migrations.py` must stop assuming Unix-only:

- `lib/python*/site-packages`;
- `bin/ah-there-it-is`.

Use a temporary Python virtual environment or another explicit platform-neutral installation boundary.

Requirements:

- discover/use the venv interpreter platform-correctly;
- support POSIX `bin` and Windows `Scripts` layouts without duplicating the whole test;
- verify the installed console entry point on each OS;
- invoke the installed package from outside the source checkout;
- preserve packaged migration/template/static/runtime coverage already provided by the test;
- preserve no-network/provider-independent behavior;
- do not weaken the test into import-only smoke.

Using `venv` + subprocess through that interpreter is preferred.

## Windows runtime/data-path verification

Keep and strengthen deterministic tests where useful for:

- `LOCALAPPDATA` default data home;
- fallback to user `AppData/Local`;
- CWD-independent database resolution;
- installed CLI path reporting.

Do not add fake tests that merely monkeypatch `sys.platform` when a behavior actually requires native Windows validation. Simulation is acceptable only for pure path functions.

## SQLite / filesystem portability policy

U24 cannot prove Windows locking semantics.

Therefore:

- do not add broad Windows skips/xfails speculatively;
- do not weaken backup/restore/WAL assertions merely because Windows may behave differently;
- document backup/restore/WAL/file-replacement/process-cleanup areas as mandatory checks for the first native Windows pilot;
- any actual Windows-specific bug discovered later must be fixed based on observed native behavior.

## Optional host preflight helper

Add a small deterministic repository helper/Just recipe if useful, e.g. `just host-check <profile>`, to make v6 preflight reproducible.

If added:

- it must not contain credentials or machine-specific paths;
- output should be concise/machine-readable;
- it must distinguish native Windows Python inside Git Bash from an MSYS Python runtime;
- it must work on U24 as well.

Do not make a new runtime dependency for this.

## Git line endings / executable metadata

Audit whether Git Bash checkout requires repository metadata protection.

Add minimal `.gitattributes` rules only if needed to guarantee shell/script/Justfile files retain usable LF semantics.

Do not globally rewrite unrelated text files or churn line endings.

Do not manually override `core.fileMode`; Git for Windows is expected to manage filesystem capability appropriately.

## CI policy

Do **not** add:

- permanent Windows CI matrix;
- duplicate Python-version jobs;
- another full application CI job.

Normal GitHub application CI remains the existing single Linux job.

Native Windows correctness is validated by the implementation host itself through the same canonical local suite and later by a real Windows pilot assignment.

Coverage remains CI-only/report-only under the already approved policy.

## Documentation/status

Update project process documentation so it accurately distinguishes:

- v4/v5 historical U24-only protocols;
- v6 host-selected protocol;
- U24 profile as established;
- Windows Git Bash profile as prepared but **pending first native pilot** at the end of Assignment 0029.

Do not call Windows first-class/validated until that pilot succeeds.

## Focused verification on U24

At minimum cover:

- Justfile parsing/execution;
- platform-neutral temporary verification helpers;
- migration-check;
- retrieval-eval;
- refactored installed-wheel smoke;
- pure Windows data-path tests;
- host-preflight helper tests if introduced;
- protocol/launcher consistency.

Then run the complete canonical verification set on U24.

## Self-review emphasis

Explicitly inspect for remaining implementation-workflow assumptions involving:

- hard-coded `/tmp`;
- `bin/` vs `Scripts/`;
- `lib/python*/site-packages`;
- PowerShell/cmd requirements;
- POSIX-only host selection rather than Bash syntax;
- accidental Windows CI duplication.

Record remaining items that require native Windows observation in `0029-r1.md`.

## Constraints

No Stage 26/domain/search behavior changes, no dependency/runtime version upgrades, no application feature work, no permanent Windows GitHub Actions job, no PowerShell implementation path, no WSL path, and no unrelated refactoring.

## Deliverable

After merge, a future launcher must be able to select one execution profile explicitly, for example:

```text
execution_profile: u24-bash
device: u24-gpt
repo_path: /home/gpt/projects/ah-there-it-is
```

or:

```text
execution_profile: windows-git-bash
device: <windows-device>
repo_path: /c/path/to/ah-there-it-is
git_bash_exe: C:\Program Files\Git\bin\bash.exe
```

The prompt, not the agent, chooses the profile.
