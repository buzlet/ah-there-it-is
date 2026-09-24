# Launcher: post-0018 evidence/usability batch

Replace `<CONTROL_SHA>` with this branch's immutable control commit SHA.

```text
Работай как autonomous batch implementation+verification agent проекта `buzlet/ah-there-it-is`.

Используй только Remote Commander на U24, устройство `u24-gpt`.

Batch control:
- branch: `queue/post-0018-autonomous-batch`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0018-evidence-usability/manifest.md`

Прочитай из указанного control SHA:
`agent-tasks/common/v5-batch.md`
и manifest.

Выполни весь batch 0019 → 0020 → 0021 → 0022 → 0023 последовательно. Для каждой задачи создай just-in-time immutable seed из точной заранее выданной спецификации, затем выполни полный v4 implementation/self-review/focused+canonical verification/PR/CI/merge lifecycle. После успешного merge самостоятельно переходи к следующей задаче без моего подтверждения.

Не меняй спецификации, не выбирай новые задачи и не реализуй Stage 26 location-truth semantics.

Если сработает stop condition v5, остановись и верни compact blocker report. После 0023 верни один compact batch report.
```
