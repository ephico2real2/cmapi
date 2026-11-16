# #222: Fable's review of PR #233, and the rulings

Fable 5.2 reviewed head `ba9e3e2` (`fable-review.md`). The coordinator ruled on each finding; OB1 run 6 (Opus 5.5 at
high) applied the accepted ones and ran each test on this Mac under the suite lock.

| Finding | Ruling | Done here | Proof |
|---|---|---|---|
| F1 (medium, not caused by this PR): the shipped portal reads `#<tab>?query`, so `#<instance>/approvals` opens its first tab | Its own defect, #236 | The comment in `core/channels.py` says which build reads the address; the test is renamed `test_each_link_names_the_instance_that_sent_it` | |
| F2 (low): the PR's test failed on the old code for the signature, not the link | Accepted | `test_email_links_by_assertion.py`, Fable's test, through `channels_for` alone | Main's `channels.py`: 3 failed, each an `AssertionError` on the link text. The branch: 8 passed with `test_email_links.py` |
| F3 (low): `instance.name` is not checked, and it goes into a URL as it is | Its own issue, #237 | | |
| F4 (low): docs/02 said no code reads a literal instance name; `tools/realm_sync.py:309` defaults the audience to `cmapi-nonprod` | Accepted | Fable's sentence in docs/02 and in the live Technical Design v2 (rev 351), with a note on #236 | `grep -c "No code reads a literal instance name" docs/02-technical-design-v2.md`: 0 |
| F5 (low): #232's default `[prod]` contradicted its check against `allowedEnvironments` | Accepted | #232's body: the check applies only when the key is written | |
