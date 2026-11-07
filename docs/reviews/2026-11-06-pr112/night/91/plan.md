# Plan

- READ FROM CODE — H1: enumerate database clients, inspect TLS settings and kind proof; test the WIP before modifying it.
- READ FROM CODE — H2: verify CA naming, requiredness, projection and rotation behavior.
- READ FROM CODE — H3: verify URI hostname against CNPG certificate documentation.
- READ FROM CODE — H4: compare docs/12 external database semantics with main and run its checks.
- READ FROM CODE — H5: render CRC and review docs/13 resource requirements and steps.
- READ FROM CODE — H6: audit all 14 WIP files for relevance, remove unsupported or unrelated changes, run final checks.
- PROPOSAL NOT OPERATED — K1: provide exact kind commands for coordinator; no runtime or cluster is available here.

Reports use MEASURED for local observations, READ FROM CODE for source/document evidence, and PROPOSAL NOT OPERATED for commands not executed. Initial claims are NOT REACHED until assessed. Fix patches target the supplied baseline commit (the WIP), apply with patch -p1 --fuzz=0, and remain uncommitted.

- READ FROM CODE — F1: verify that the bad-CA proof actually supplies a wrong CA when run against pre-fix manifests, then correct its generator only if a behavioral regression test fails.
