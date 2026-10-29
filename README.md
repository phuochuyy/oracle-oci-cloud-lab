# Oracle on OCI — BANKDB to Autonomous Database (Always Free)

> Status: **done** — one run, then every cloud resource deleted (only a compartment and a budget alert are
> kept; both cost nothing). The on-premises side is the [performance lab](https://github.com/phuochuyy/oracle-performance-tuning-lab)'s
> BANKDB on Oracle 23.26 (KVM lab).

## Results

| Step | Result | Evidence |
|------|--------|----------|
| Export (on-premises, PERF PDB on orcl3) | 5 tables, 8 M transactions, consistent at one SCN (`flashback_scn`), `COMPRESSION=ALL`, `ENCRYPTION=ALL` AES256 password mode: **1 file, 172.5 MB, 41 s** | [`results/01-expdp.log`](results/01-expdp.log) |
| Transfer | host → private bucket (`NoPublicAccess`), multipart with per-part MD5: **49 s** | — |
| Import into ADB | `DBMS_DATAPUMP` inside the ADB, reading the dump straight from Object Storage as **resource principal** (dynamic group of this one ADB + read-only policy on the one bucket — no token in the database): **2 min 55 s, 0 errors** | [`results/02-import.log`](results/02-import.log) |
| Verification | row counts + `ora_hash` checksums of all 5 tables, source **AS OF the export SCN** vs ADB: **identical** | [`checksums-source.txt`](results/checksums-source.txt), [`checksums-adb.txt`](results/checksums-adb.txt) |
| Structure | interval partitioning kept (25 partitions), 11 indexes VALID, 13 constraints validated — but **compression lost**: 12 BASIC-compressed partitions on-premises, 0 on the ADB (probably my `SEGMENT_ATTRIBUTES=0` transform; not verified) | [`results/03-structure-and-flashback.txt`](results/03-structure-and-flashback.txt) |
| Logical recovery (drill 2b of the backup lab) | a bad batch zeroed 68,571 balances and committed; `FLASHBACK TABLE` was **still running after 36 min** (1.6 M undo records, 1 ECPU) → killed; repaired from my own dump instead (ACCOUNTS imported as a copy + one `MERGE`): **25 s, checksums identical to the source again** | same |
| Data Safe | Security Assessment: **0 high, 0 medium**, 6 low, 13 advisory, 59 to evaluate; User Assessment: 9 users, 4 critical (all privileged: ADMIN, Data Safe's own user, 2 locked Oracle accounts) | [`results/04-data-safe.txt`](results/04-data-safe.txt) |

Scripts: [`checksums.py`](scripts/checksums.py), [`import_adb.py`](scripts/import_adb.py),
[`access_model.py`](scripts/access_model.py), [`structure_and_flashback.py`](scripts/structure_and_flashback.py).

## Re-run 2026-10-30 — same steps, new ADB, everything deleted again

| Step | Run 1 (10-29) | Run 2 (10-30) |
|------|---------------|---------------|
| Export | 41 s, 172,503,040 bytes | 43 s, **same size** |
| Source checksums | — | **identical to run 1** (PERF unchanged) |
| Upload | 49 s | first attempt **hung** (see below), second 52 s |
| ADB | 26ai, 23.26.4.1 | 26ai, 23.26.4.1 |
| Access model | SYSDBA refused, ORA-01031 ×3, TDE 6/7, TCPS, 13 audit policies | identical |
| Import (`DBMS_DATAPUMP`, resource principal) | 2 min 55 s, 0 errors | 2 min 48 s; one `ORA-20404` on the first `list_objects` — the new policy needed a few seconds, the retry loop saw the file at once |
| Checksums ADB vs source | identical | **identical** |
| Structure | interval partitions kept, compression lost | same (compression lost again — the import, not chance) |
| `FLASHBACK TABLE` of 68,571 rows | not finished after 36 min → killed | **not finished after 40.4 min** (1.75 M undo records) → killed |
| Repair from my own export | 25 s | 31 s, checksums identical again |
| Data Safe | 0 high / 0 medium / 6 low / 13 advisory; 9 users | identical |
| Clean-up | every type checked: 0 left | every type checked: 0 left, spend 0.00 |

Evidence: `results/rerun2-*`.

**What the re-run added:** the host's public IP changed in the middle of the upload (the ISP reconnected). The
OCI CLI's upload threads had no connection left and waited — 27 min, 0 of 6 parts done, no error. Stopped,
the unfinished multipart upload aborted (no orphan parts in the bucket), uploaded again with 2 parallel parts,
`--connection-timeout 10 --read-timeout 60` and an overall `timeout`: 52 s. The same IP change broke the ADB
access list (it allowed only the old address): updated to the new one, the old one removed. An IP allow-list
on a home connection needs checking before every session.

## On-premises lab vs Autonomous Database — what changes for the DBA

| | On-premises lab (23.26.1) | Autonomous Database Always Free (26ai = 23.26.4.1) |
|---|---|---|
| Version / patching | I apply RUs myself (patch inventory with Ansible) | **3 RUs ahead** of my lab on day one; Oracle patches in a maintenance window (`REGULAR`, 2 h, shown in the API) — no OPatch, no choice of RU |
| SYSDBA, OS | everything | `SYSDBA` login refused (ORA-01017); no OS: `CREATE DIRECTORY ... '/tmp'` succeeds but is remapped to `/u03/dbfs/<guid>/data/tmp`; alert log location not visible |
| Instance / storage | parameters, tablespaces, redo, FRA — my job (and my incident: a full `+FRA` hung the primary) | `ALTER SYSTEM SET`, `CREATE TABLESPACE`, `SWITCH LOGFILE`: **ORA-01031**; ARCHIVELOG and Flashback on, managed by Oracle |
| Backup / PITR | RMAN level 0/1, offload to the standby, 14 timed restore drills | automatic, retention 60 days shown — but **Always Free cannot restore or do point-in-time recovery**, and no manual backups (paid ADB can); one automatic incremental backup appeared (12:09–12:11 UTC, 22 min after creation, right after my import), `is-restorable` empty — it exists, but I could not use it |
| Logical recovery | Flashback Drop / Table / Query: < 1 s for 4,285 rows | same features — but on 1 ECPU `FLASHBACK TABLE` for 68,571 rows did not finish in 36 min, and with no restore/PITR the way out was **my own export** (25 s) |
| Encryption at rest | TDE set up by me (keystore, online encryption, standby keys) | TDE on by default: 6 of 7 tablespaces (the 7th is Oracle's read-only `SAMPLESCHEMA`) |
| Encryption in transit | native encryption AES256 that I required in `sqlnet.ora` | TLS only, and **mTLS required** (wallet); network ACL = the lab host's IP only |
| Audit | 5 policies I wrote + volume tuning | 13 unified policies enabled out of the box |
| Masking | Data Redaction on `CARDS.PAN` in SECPDB | **none**: the dump came from PERF, which never had the policy — controls do not travel with a table export; Data Safe flags it ("No data redaction policies found") |
| Assessment | my CIS-style script (DBSAT needs a support contract): 27 FAIL → 0 | Data Safe Security Assessment, free for ADB: 0 high / 0 medium |

## Data Safe — what it reported (after the import)

- **Low (6):** 2 users with unlimited concurrent sessions, a profile with password rollover > 14 days,
  password lifetime/reuse limits (informational: set for all users), 1 user with unlimited idle time, 1 logon trigger + 2 disabled triggers, TDE (informational: 6 encrypted
  tablespaces, none unencrypted).
- **Advisory (13):** SQL Firewall, Database Vault, Privilege Analysis never run, no Data Redaction, no
  fine-grained audit, no object-action audit, audit trail in SYSAUX, …
- **User Assessment:** ADMIN (open, `PDB_DBA`, `AUDIT_ADMIN`, `DV_ADMIN`) and `DS$ADMIN` (Data Safe's own
  user) critical by design; `GGADMIN`, `RMAN$CATALOG` (critical) and `ADBSNMP` (high) privileged but **locked**. The schema
  `BANK` was created `NO AUTHENTICATION` (schema-only), as in the on-premises security lab.

Compared with my own script: the same families of checks (users/profiles, privileges, audit, encryption,
configuration); Data Safe adds the "advisory" layer (Vault, SQL Firewall, Privilege Analysis) — the same
items my security lab lists as not built.

## Cost and clean-up

Every resource was created with the Always Free flag or is free (ADB `isFreeTier`, 1 ECPU, 20 GB; one bucket
with 172 MB; Data Safe for ADB). A tenancy budget of 1 SGD/month alerts on any actual spend (1 %) or forecast
(100 %). After the run, each deletion checked by
listing the resource type again:

| Deleted | Check |
|---------|-------|
| Data Safe target, then its 2 security + 2 user assessments (deleting the target left them behind) | 0 left |
| Autonomous Database | `TERMINATED` — the first `delete --wait-for-state` returned without effect; the second call worked |
| dump object + bucket | `BucketNotFound` |
| IAM policy + dynamic group | 0 left |
| wallet, staged dump on the host, export files and directory object on prm3 | removed |

Kept: the compartment and the budget alert (no cost). Credit used: none expected — everything was Always Free.

## Problems on the way

- The host had no `ensurepip` (no sudo to install `python3-venv`): the OCI CLI's virtualenv was created
  `--without-pip` and filled with the pip of an existing one (`pip --python`).
- CLI 3.95: budgets are `oci budgets budget budget create` — my first call failed and I only saw it because
  the budget id came back empty.
- The first export failed: the SCN I passed was empty (sqlplus output with leading spaces); `expdp` stopped
  at the parameter file (`LRM-00116`).
- No `impdp` client on the host: the import runs as `DBMS_DATAPUMP` inside the ADB, the dump read directly
  from Object Storage (`ku$_file_type_uridump_file`, credential `OCI$RESOURCE_PRINCIPAL`).
- The dynamic group's matching rule shows as `None` through the classic IAM API; the identity-domain API
  shows it (`ALL {resource.id = '<adb>'}`) — this tenancy uses identity domains.
- `ENABLE ROW MOVEMENT` is DDL: after it, a flashback query to before the bad batch fails with `ORA-01466` — so once `FLASHBACK TABLE` was killed, undo could not be used at all. Row movement has to be enabled *before* an accident, not during the repair.
