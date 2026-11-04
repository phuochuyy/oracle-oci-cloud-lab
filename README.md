# Oracle on OCI

The banking dataset of the [performance lab](https://github.com/phuochuyy/oracle-performance-tuning-lab) migrated to Oracle Autonomous Database on the Always Free tier, verified table by table, then every cloud resource deleted.

## What is in it

- **Migration**: a consistent, compressed and encrypted Data Pump export, imported inside the database from Object Storage with a resource principal, so no password is stored.
- **Verification**: row counts and checksums against the source at the export point.
- **What changes for a DBA**: no SYSDBA or server access, patching done by Oracle, no point-in-time restore on the free tier.
- **Recovery without restore**: a bad update repaired from my own export.
- **Cost control**: a budget alert, and a scripted clean-up with a check of what is left.

## Where to look

- [Results and comparison with on-premises](docs/details.md)
- [Scripts](scripts/)
- [Evidence](results/)
