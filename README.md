# Oracle on OCI — BANKDB to Autonomous Database (Always Free)

The banking dataset of the [performance lab](https://github.com/phuochuyy/oracle-performance-tuning-lab) (8 M
transactions, Oracle 23.26 on-premises) migrated to Autonomous Database 26ai three times, verified table by table,
then every cloud resource deleted (cost 0.00; only a compartment and a budget alert are kept).

| Step | Run 1 | Run 2 | Run 3 |
|------|-------|-------|-------|
| Export: consistent at one SCN, `COMPRESSION=ALL`, AES256 password encryption | 41 s, 172.5 MB | 43 s | 38 s ([script](scripts/export_perf.sh)) |
| Import inside the ADB from Object Storage, **resource principal** (no stored credential) | 2 min 55 s | 2 min 48 s | 3 min 00 s (185 s wall) |
| Row counts + checksums of all 5 tables, source AS OF the export SCN vs ADB | identical | identical | identical |
| Bad batch (68,571 balances zeroed): `FLASHBACK TABLE` on 1 ECPU | > 36 min, killed | > 40.4 min, killed | skipped |
| Repair from my own dump (no PITR on Always Free) | 25 s | 31 s | 18 s |
| Data Safe security assessment | 0 high / 0 medium | 0 high / 0 medium | 0 high / 0 medium |

- What changes for a DBA: no SYSDBA or OS, Oracle patches (3 RUs ahead of the lab on day one), TDE and 13 audit
  policies on by default, mTLS + IP access list; compression and Data Redaction did not travel with the export.
- Run 3 lessons: a resource principal keeps its token after a dynamic-group fix (re-enable it); Data Safe leaves
  crypto assessments behind when a target is deleted (runs 1–2 missed them — found and deleted).
- Full write-up (DBA comparison table, Data Safe findings, clean-up checks, problems and my mistakes):
  [`docs/details.md`](docs/details.md) · cloud lifecycle as one script: [`scripts/oci_lab.sh`](scripts/oci_lab.sh) ·
  evidence: [`results/`](results/).
