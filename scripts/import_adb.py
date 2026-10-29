"""Import the BANKDB dump from Object Storage into Autonomous Database with DBMS_DATAPUMP (no impdp client needed).

usage: import_adb.py
The ADB reads the bucket as itself (resource principal: dynamic group + read-only policy on the one bucket),
so no token or key is stored in the database. Region/namespace from ../oci.env, passwords from ../lab.env.
Prints the Data Pump log with the namespace masked.
"""
import pathlib
import time

import oracledb

HERE = pathlib.Path(__file__).resolve().parent.parent
CRED = "OCI$RESOURCE_PRINCIPAL"


def env(name):
    lines = (HERE / name).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.lstrip().startswith("#"))


def main():
    e, o, w = env("lab.env"), env("oci.env"), str(HERE / "wallet")
    base = f"https://objectstorage.{o['OCI_REGION']}.oraclecloud.com/n/{o['OCI_NAMESPACE']}/b/bankdb-dump/o/"
    mask = lambda s: s.replace(o["OCI_NAMESPACE"], "<namespace>")
    con = oracledb.connect(user="admin", password=e["ADB_ADMIN_PASSWORD"], dsn="bankadb_low", config_dir=w,
                           wallet_location=w, wallet_password=e["ADB_WALLET_PASSWORD"])
    cur = con.cursor()
    cur.callproc("dbms_cloud_admin.enable_resource_principal")
    print("resource principal enabled")
    for i in range(12):  # a new policy can take a minute to reach the service
        try:
            names = [r[0] for r in cur.execute("select object_name from dbms_cloud.list_objects(:c, :u)", c=CRED, u=base)]
            print("objects the ADB can see in the bucket:", names)
            break
        except oracledb.Error as ex:
            print("list_objects:", mask(str(ex).split("\n")[0]), "- retry in 10 s")
            time.sleep(10)
    cur.execute("select count(*) from dba_users where username = 'BANK'")
    if cur.fetchone()[0] == 0:
        cur.execute("create user bank no authentication quota unlimited on data")  # schema only, nobody logs in
    print("schema BANK ready (no authentication)")
    cur.execute("select count(*) from dba_tables where owner = 'BANK' and table_name = 'TRANSACTIONS'")
    if cur.fetchone()[0]:
        print("BANK.TRANSACTIONS exists: import already done, only printing its log")
    else:
        import_dump(cur, base, e["DP_ENC_PASSWORD"])
    print_log(cur, mask)


def import_dump(cur, base, encpw):
    t0 = time.time()
    state = cur.var(str)
    cur.execute("""
declare
  h  number;
  st varchar2(30);
begin
  h := dbms_datapump.open(operation => 'IMPORT', job_mode => 'FULL', job_name => 'BANKDB_IMP');
  dbms_datapump.add_file(h, filename => :dump, directory => :cred, filetype => dbms_datapump.ku$_file_type_uridump_file);
  dbms_datapump.add_file(h, filename => 'bankdb_imp.log', directory => 'DATA_PUMP_DIR',
                         filetype => dbms_datapump.ku$_file_type_log_file, reusefile => 1);
  dbms_datapump.set_parameter(h, 'ENCRYPTION_PASSWORD', :encpw);
  -- the on-premises tablespaces and storage clauses do not exist here: everything goes to DATA
  dbms_datapump.metadata_transform(h, 'SEGMENT_ATTRIBUTES', 0);
  dbms_datapump.set_parallel(h, 1);
  dbms_datapump.start_job(h);
  dbms_datapump.wait_for_job(h, st);
  :state := st;
end;""", dump=base + "bankdb_01.dmp", cred=CRED, encpw=encpw, state=state)
    print(f"import job {state.getvalue()} in {time.time() - t0:.0f} s")


def print_log(cur, mask):
    cur.callproc("dbms_output.enable", [None])
    cur.execute("""
declare f utl_file.file_type; l varchar2(4000);
begin
  f := utl_file.fopen('DATA_PUMP_DIR', 'bankdb_imp.log', 'r');
  loop begin utl_file.get_line(f, l); dbms_output.put_line(l); exception when no_data_found then exit; end; end loop;
  utl_file.fclose(f);
end;""")
    line, status = cur.var(str), cur.var(int)
    while True:
        cur.callproc("dbms_output.get_line", (line, status))
        if status.getvalue() != 0:
            break
        print(mask(line.getvalue() or ""))


if __name__ == "__main__":
    main()
