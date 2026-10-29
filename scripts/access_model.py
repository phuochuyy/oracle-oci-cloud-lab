"""What an on-premises DBA can and cannot do as ADMIN on Autonomous Database: each statement once, result or error.

usage: access_model.py   (ADMIN through the mTLS wallet in ../wallet, password from ../lab.env)
"""
import pathlib

import oracledb

HERE = pathlib.Path(__file__).resolve().parent.parent

# (what an on-prem DBA would do, statement)
STATEMENTS = [
    ("connect as SYSDBA", None),
    ("change an instance parameter", "alter system set db_recovery_file_dest_size = 10g"),
    ("create a tablespace", "create tablespace lab_ts datafile size 10m"),
    ("switch a redo log", "alter system switch logfile"),
    ("read the alert log location", "select value from v$diag_info where name = 'Diag Trace'"),
    ("create a directory on the OS", "create or replace directory lab_tmp as '/tmp'"),
    ("TDE: keystore and encrypted tablespaces",
     "select w.status || '/' || w.wallet_type || ', encrypted tablespaces: ' || "
     "(select count(*) from dba_tablespaces where encrypted = 'YES') || ' of ' || "
     "(select count(*) from dba_tablespaces) from v$encryption_wallet w where rownum = 1"),
    ("protocol of this session", "select sys_context('userenv', 'network_protocol') from dual"),
    ("unified audit policies enabled",
     "select count(*) || ': ' || listagg(policy_name, ', ') within group (order by policy_name) "
     "from audit_unified_enabled_policies"),
    ("archivelog mode / flashback", "select log_mode || ' / flashback ' || flashback_on from v$database"),
]


def env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))


def main():
    e, w = env(HERE / "lab.env"), str(HERE / "wallet")
    params = dict(dsn="bankadb_low", config_dir=w, wallet_location=w, wallet_password=e["ADB_WALLET_PASSWORD"])
    for what, sql in STATEMENTS:
        if sql is None:  # SYS / SYSDBA does not exist for the customer
            try:
                oracledb.connect(user="sys", password=e["ADB_ADMIN_PASSWORD"], mode=oracledb.AUTH_MODE_SYSDBA,
                                 **params).close()
                res = "connected"
            except oracledb.Error as ex:
                res = str(ex).split("\n")[0]
            print(f"{what:<42} {res}")
            continue
        with oracledb.connect(user="admin", password=e["ADB_ADMIN_PASSWORD"], **params) as con, con.cursor() as cur:
            try:
                cur.execute(sql)
                if sql.lstrip().startswith("select"):
                    row = cur.fetchone()
                    res = row[0] if row else "no rows (not visible to ADMIN)"
                else:
                    res = "done"
            except oracledb.Error as ex:
                res = str(ex).split("\n")[0]
            print(f"{what:<42} {str(res)[:150]}")


if __name__ == "__main__":
    main()
