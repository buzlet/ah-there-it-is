# Launcher: post-0023 Stage 26 batch

Replace `<CONTROL_SHA>` with this control branch's immutable commit SHA.

```text
Работай как autonomous batch implementation+verification agent проекта `buzlet/ah-there-it-is`.

Используй только Remote Commander на U24, устройство `u24-gpt`.

Batch control:
- branch: `queue/post-0023-stage26-batch`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0023-stage26/manifest.md`

Прочитай из указанного control SHA:
`agent-tasks/common/v5-batch.md`
и manifest.

Проверь start prerequisite и затем выполни весь batch:

`0024 → 0025 → 0026 → 0027 → 0028`

последовательно.

Для каждой задачи создай just-in-time immutable seed из точной спецификации, затем выполни полный v4 implementation/self-review/focused+canonical verification/PR/CI/merge lifecycle. После успешного merge самостоятельно переходи к следующей задаче без моего подтверждения.

Принятые Stage 26 решения не переоткрывай. Не выбирай новые задачи и не переходи к duplicate/quantity, undo/delete, auth/multi-user или новым search algorithms.

При stop condition v5 остановись с compact blocker report. После 0028 верни один compact batch report.
```
