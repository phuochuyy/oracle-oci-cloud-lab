#!/bin/bash
# Export BANKDB (5 tables of PDB PERF on orcl3, prm3) for the OCI migration: consistent at one SCN, compressed,
# AES256-encrypted in password mode. Same parameters as run 1 (results/01-expdp.log), now as a script.
# usage (from the host): scripts/export_perf.sh <label>
#   -> stage/bankdb_01.dmp (git-ignored), results/<label>-expdp.log; prints "SCN <n>" for checksums.py source <n>
# DP_ENC_PASSWORD comes from ../lab.env and travels over ssh stdin into a mode-600 parfile on prm3 (expdp has no
# other non-interactive way to take it), removed right after the export. Never on a command line.
# Clean-up afterwards: scripts/export_perf.sh --clean (dump, log, directory object on prm3).
set -eu
H=$(cd "$(dirname "$0")/.." && pwd)
D=/u01/app/oracle/oci_exp   # oracle-owned (/u02 is root-owned)
P="ssh -o BatchMode=yes oracle@prm3"
if [ "${1:-}" = --clean ]; then
  $P 'bash -s' <<EOF
. ~/.bash_profile >/dev/null 2>&1; export ORACLE_PDB_SID=PERF
rm -rf $D
echo 'drop directory oci_exp;' | sqlplus -s / as sysdba | grep -vE '^$'
EOF
  exit 0
fi
label=${1:?usage: export_perf.sh <label> | --clean}
. "$H/lab.env"; : "${DP_ENC_PASSWORD:?set in lab.env}"
mkdir -p "$H/stage"
$P 'bash -s' > "$H/stage/export-$label.out" 2>&1 <<EOF
# profile first: /etc/bashrc reads unset variables and would abort under set -u
. ~/.bash_profile >/dev/null 2>&1
set -eu
export ORACLE_PDB_SID=PERF
mkdir -p $D; rm -f $D/bankdb_*.dmp $D/bankdb_exp.log
echo "create or replace directory oci_exp as '$D';" | sqlplus -s / as sysdba | grep -vE '^$'
scn=\$(printf 'set heading off feedback off pages 0\nselect current_scn from v\$database;\n' | sqlplus -s / as sysdba | tr -d ' \t\n')
case \$scn in ''|*[!0-9]*) echo "bad SCN '\$scn'"; exit 1 ;; esac
echo "SCN \$scn"
par=\$(mktemp); chmod 600 \$par
cat > \$par <<'PAR'
directory=oci_exp
dumpfile=bankdb_%U.dmp
filesize=200M
logfile=bankdb_exp.log
tables=BANK.BRANCHES,BANK.CUSTOMERS,BANK.ACCOUNTS,BANK.CARDS,BANK.TRANSACTIONS
flashback_scn=SCN_HERE
compression=ALL
encryption=ALL
encryption_mode=PASSWORD
encryption_algorithm=AES256
encryption_password=${DP_ENC_PASSWORD}
exclude=statistics
logtime=all
metrics=Y
PAR
sed -i "s/^flashback_scn=SCN_HERE\$/flashback_scn=\$scn/" \$par
t0=\$(date +%s)
rc=0; expdp "'/ as sysdba'" parfile=\$par >/dev/null 2>&1 || rc=\$?
rm -f \$par
echo "expdp rc=\$rc wall \$(( \$(date +%s) - t0 )) s"
ls -l $D/bankdb_*.dmp
EOF
cat "$H/stage/export-$label.out"
scp -q oracle@prm3:$D/bankdb_exp.log "$H/results/$label-expdp.log"
scp -q oracle@prm3:$D/bankdb_01.dmp "$H/stage/bankdb_01.dmp"
ls -l "$H/stage/bankdb_01.dmp"
grep -E "successfully completed|ORA-" "$H/results/$label-expdp.log" | tail -3
