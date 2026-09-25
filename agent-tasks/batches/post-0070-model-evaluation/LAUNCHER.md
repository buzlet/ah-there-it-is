# Launcher — sandbox batch 0081–0083

Immutable control is issued externally for branch queue/post-0070-model-evaluation-sandbox.

Expected upstream start main:
153435ef3272a134d85ff02bcc370b8121b0708a

Source artifact:
sandbox-bundle-153435ef3272a134d85ff02bcc370b8121b0708a

Implementation branch:
feat/model-evaluation-0081-0083

Execution:
- host_profile: chatgpt-sandbox
- execution_channel: sandbox
- execution_user: sandbox
- workdir: /mnt/data/model-evaluation-0081-0083

Use sandbox/container execution for files, Python, Make and tests.
Use GitHub connector for GitHub reads/writes/artifact/control/branch/commit/PR actions.

Do not use shell network, git fetch/push, curl/wget or online pip/uv.

Extract the exact artifact, verify manifest SHA, run make sandbox-bootstrap, then
materialize exact control specs via GitHub connector and create matching local +
remote seed commits.

Use GNU Make. Do not install/use just.

Read only AGENTS.md, protocol v8, sandbox-execution rules, exact issued
manifest/specs and relevant evaluation source/tests. Do not recursively read archive.

Execute strictly 0081 -> 0082 -> 0083.
