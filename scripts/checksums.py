"""Row counts + checksums of the five BANKDB tables — same expressions as the performance lab's 03_verify.sql.

usage: checksums.py source <scn>   BANK in PERF on prm3, AS OF the export SCN (flashback query)
       checksums.py adb            BANK in the Autonomous Database (mTLS wallet in ../wallet)
Prints one line per table: name, rows, checksum. Credentials from ../lab.env and the performance lab's lab.env.
"""
import pathlib
import sys

import oracledb

HERE = pathlib.Path(__file__).resolve().parent.parent
TABLES = {
    "BRANCHES": "branch_id || '|' || branch_code || '|' || city",
    "CUSTOMERS": "customer_id || '|' || national_id || '|' || segment || '|' || to_char(dob, 'YYYYMMDD')",
    "ACCOUNTS": "account_id || '|' || customer_id || '|' || status || '|' || balance",
    "CARDS": "card_id || '|' || pan || '|' || status",
    "TRANSACTIONS": "txn_id || '|' || account_id || '|' || to_char(txn_ts, 'YYYYMMDDHH24MISS') || '|' || amount || '|' || status",
}


def env(path):
    out = {}
    for line in pathlib.Path(path).expanduser().read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.split("#")[0].strip().strip("'\"")
    return out


def connect(target):
    if target == "source":
        e = env("~/work/oracle-performance-tuning-lab/lab.env")
        # by IP: the host does not resolve the lab's names
        return oracledb.connect(user="bank", password=e["BANK_PASSWORD"], dsn="192.168.106.10:1521/perf.rac")
    e, w = env(HERE / "lab.env"), HERE / "wallet"
    return oracledb.connect(user="admin", password=e["ADB_ADMIN_PASSWORD"], dsn="bankadb_low", config_dir=str(w),
                            wallet_location=str(w), wallet_password=e["ADB_WALLET_PASSWORD"])


def main():
    target = sys.argv[1]
    as_of = f" as of scn {int(sys.argv[2])}" if target == "source" else ""
    with connect(target) as con, con.cursor() as cur:
        # balance/amount are converted to text inside ora_hash: fix the decimal separator on both sides
        cur.execute("alter session set nls_numeric_characters = '.,'")
        for t, expr in TABLES.items():
            cur.execute(f"select count(*), sum(ora_hash({expr})) from bank.{t.lower()}{as_of}")
            rows, chk = cur.fetchone()
            print(f"{t:<13} {rows:>9} {chk}")


if __name__ == "__main__":
    main()
