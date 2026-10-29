"""Repair BANK.ACCOUNTS on the ADB from my own Data Pump export (Always Free has no restore / PITR).

usage: repair_from_dump.py
Imports ACCOUNTS from the dump in Object Storage as ACCOUNTS_RESTORE (REMAP_TABLE), puts the balances back
with one MERGE, drops the copy and prints the table's checksum (compare with checksums-source.txt).
"""
import pathlib
import time

import oracledb

HERE = pathlib.Path(__file__).resolve().parent.parent
CHK = ("select count(*), sum(ora_hash(account_id || '|' || customer_id || '|' || status || '|' || balance)) "
       "from bank.accounts")


def env(name):
    lines = (HERE / name).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.lstrip().startswith("#"))


def main():
    e, o, w = env("lab.env"), env("oci.env"), str(HERE / "wallet")
    dump = (f"https://objectstorage.{o['OCI_REGION']}.oraclecloud.com/n/{o['OCI_NAMESPACE']}"
            "/b/bankdb-dump/o/bankdb_01.dmp")
    con = oracledb.connect(user="admin", password=e["ADB_ADMIN_PASSWORD"], dsn="bankadb_tp", config_dir=w,
                           wallet_location=w, wallet_password=e["ADB_WALLET_PASSWORD"])
    cur = con.cursor()
    cur.execute("alter session set nls_numeric_characters = '.,'")
    print("accounts now:", cur.execute(CHK).fetchone())
    t0 = time.time()
    state = cur.var(str)
    cur.execute("""
declare
  h  number;
  st varchar2(30);
begin
  h := dbms_datapump.open(operation => 'IMPORT', job_mode => 'TABLE', job_name => 'ACCOUNTS_REPAIR');
  dbms_datapump.add_file(h, filename => :dump, directory => 'OCI$RESOURCE_PRINCIPAL',
                         filetype => dbms_datapump.ku$_file_type_uridump_file);
  dbms_datapump.add_file(h, filename => 'accounts_repair.log', directory => 'DATA_PUMP_DIR',
                         filetype => dbms_datapump.ku$_file_type_log_file, reusefile => 1);
  dbms_datapump.set_parameter(h, 'ENCRYPTION_PASSWORD', :encpw);
  dbms_datapump.metadata_filter(h, 'SCHEMA_EXPR', 'IN (''BANK'')');
  dbms_datapump.metadata_filter(h, 'NAME_EXPR', 'IN (''ACCOUNTS'')');
  -- only the rows: no indexes, constraints or grants on the copy
  dbms_datapump.metadata_filter(h, 'EXCLUDE_PATH_EXPR', 'IN (''INDEX'', ''CONSTRAINT'', ''REF_CONSTRAINT'', ''GRANT'')');
  dbms_datapump.metadata_remap(h, 'REMAP_TABLE', 'ACCOUNTS', 'ACCOUNTS_RESTORE');
  dbms_datapump.metadata_transform(h, 'SEGMENT_ATTRIBUTES', 0);
  dbms_datapump.start_job(h);
  dbms_datapump.wait_for_job(h, st);
  :state := st;
end;""", dump=dump, encpw=e["DP_ENC_PASSWORD"], state=state)
    t1 = time.time()
    print(f"ACCOUNTS_RESTORE imported: {state.getvalue()} in {t1 - t0:.0f} s")
    cur.execute("""merge into bank.accounts a using bank.accounts_restore r on (r.account_id = a.account_id)
                   when matched then update set a.balance = r.balance where a.balance <> r.balance""")
    print("balances put back:", cur.rowcount)
    con.commit()
    cur.execute("drop table bank.accounts_restore purge")
    after = cur.execute(CHK).fetchone()
    print(f"accounts after the repair: {after}, total {time.time() - t0:.0f} s")
    con.close()


if __name__ == "__main__":
    main()
