| ID | Verdict | Evidence |
| --- | --- | --- |
| H1 | PLAUSIBLE | READ FROM CODE — all four plain-manifest clients inherit verify-full and CNPG CA; libpq/kind enforcement not run. Legacy Helm is outside this deployment path. |
| H2 | PLAUSIBLE | READ FROM CODE — correct public CA projection; optional supports external DB but libpq requires the file for CNPG. Eventual updates, no app restart; rotation not operated. |
| H3 | CONFIRMED | READ FROM CODE — v1.30.1 URI uses cmapi-db-rw.cmapi; GetClusterAltDNSNames includes that exact DNS SAN. No live certificate inspected. |
| H4 | PLAUSIBLE | MEASURED — all docs/12 code blocks identical to main; READ FROM CODE — explicit URI TLS options override defaults. External TLS runtime not reached. |
| H5 | CONFIRMED | MEASURED — CRC renders; requests remain 576/672 Mi. READ FROM CODE — docs/13 step order remains valid. CRC runtime not reached. |
| H6 | REFUTED | READ FROM CODE — WIP docs/08 claimed uncompleted kind results as measured; removed that change. Other 13 files support #91. |
| K1 | NOT REACHED | PROPOSAL NOT OPERATED — kind runtime unavailable; coordinator proof required. |
| F1 | CONFIRMED | MEASURED — proof failed to inject a wrong CA on pre-fix specs; corrected generator passes 16 cases after failing before. |
