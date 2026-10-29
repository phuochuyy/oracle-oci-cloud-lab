"""After the import: did the structure survive, and does logical recovery work as on-premises?

usage: structure_and_flashback.py
1. partitions, indexes, constraints of BANK on the ADB
2. drill 2b of the backup lab, on the ADB: a bad batch zeroes 1/7 of the balances and commits, then
   FLASHBACK TABLE to the timestamp before it — timed, checked with the same checksum as the migration
"""
import pathlib
import time

import oracledb

HERE = pathlib.Path(__file__).resolve().parent.parent
CHK = ("select count(*), sum(ora_hash(account_id || '|' || customer_id || '|' || status || '|' || balance)) "
       "from bank.accounts")


def env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))


def main():
    e, w = env(HERE / "lab.env"), str(HERE / "wallet")
    con = oracledb.connect(user="admin", password=e["ADB_ADMIN_PASSWORD"], dsn="bankadb_tp", config_dir=w,
                           wallet_location=w, wallet_password=e["ADB_WALLET_PASSWORD"])
    cur = con.cursor()
    cur.execute("alter session set nls_numeric_characters = '.,'")
    print("== structure")
    for label, sql in [
        ("TRANSACTIONS partitioning", "select partitioning_type || ' interval ' || nvl(interval, '-') || ', ' || "
         "(select count(*) from dba_tab_partitions where table_owner = 'BANK' and table_name = 'TRANSACTIONS') || "
         "' partitions' from dba_part_tables where owner = 'BANK' and table_name = 'TRANSACTIONS'"),
        ("compression of partitions", "select listagg(c, ', ') within group (order by c) from (select compression || "
         "'/' || nvl(compress_for, '-') || ': ' || count(*) c from dba_tab_partitions where table_owner = 'BANK' "
         "and table_name = 'TRANSACTIONS' group by compression, compress_for)"),
        ("indexes", "select count(*) || ': ' || listagg(index_name || ' (' || status || ')', ', ') within group "
         "(order by index_name) from dba_indexes where owner = 'BANK'"),
        ("constraints", "select count(*) || ' (' || listagg(distinct constraint_type, '') || '), not validated: ' || "
         "sum(case when validated <> 'VALIDATED' then 1 else 0 end) from dba_constraints where owner = 'BANK' "
         "and constraint_type in ('P', 'R', 'U', 'C') and constraint_name not like 'SYS_C%'"),
        ("tablespace of the tables", "select listagg(distinct nvl(tablespace_name, '(partitioned)'), ', ') "
         "from dba_tables where owner = 'BANK'"),
    ]:
        print(f"{label:<28} {cur.execute(sql).fetchone()[0]}")

    print("== drill 2b on the ADB: bad batch, then FLASHBACK TABLE")
    before = cur.execute(CHK).fetchone()
    print("accounts before:", before)
    cur.execute("select systimestamp from dual")
    ts = cur.fetchone()[0]
    time.sleep(2)  # flashback works to SCN granularity; leave a clear gap before the bad batch
    cur.execute("update bank.accounts set balance = 0 where mod(account_id, 7) = 0")
    print("bad batch:", cur.rowcount, "balances set to 0")
    con.commit()
    print("accounts after the batch:", cur.execute(CHK).fetchone())
    t0 = time.time()
    cur.execute("alter table bank.accounts enable row movement")
    cur.execute("flashback table bank.accounts to timestamp :ts", ts=ts)
    rto = time.time() - t0
    after = cur.execute(CHK).fetchone()
    cur.execute("alter table bank.accounts disable row movement")
    print("accounts after FLASHBACK TABLE:", after)
    print(f"result: {'PASS' if after == before else 'FAIL'}, flashback {rto:.1f} s")
    con.close()


if __name__ == "__main__":
    main()
