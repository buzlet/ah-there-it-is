# Launcher template

Replace `<CONTROL_SHA>` with the immutable commit SHA of this control branch.

```text
Работай как autonomous batch implementation+verification agent проекта `buzlet/ah-there-it-is`.

Используй только Remote Commander на U24, устройство `u24-gpt`.

Assignment 0013 уже выполняется отдельно и не входит в batch. Начинай batch только после того, как 0013 успешно влит в main.

Batch control:
- branch: `queue/post-0013-autonomous-batch`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0013-hardening/manifest.md`

Сначала прочитай из указанного control SHA:
`agent-tasks/common/v5-batch.md`
и batch manifest.

Выполни весь batch 0014→0018 последовательно. Для каждой задачи создай just-in-time immutable seed из точной заранее выданной спецификации, затем выполни полный implementation/self-review/focused+canonical verification/PR/CI/merge lifecycle. После успешного merge самостоятельно переходи к следующей задаче без моего подтверждения.

Не выбирай новые задачи, не меняй спецификации и не переходи к product Stage 26. Остановись только по stop condition из v5.

В конце верни один компактный batch report. Если batch остановлен, верни compact blocker report с уже завершёнными задачами.
```
