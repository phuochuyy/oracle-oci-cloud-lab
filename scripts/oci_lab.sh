#!/bin/bash
# OCI side of a run, from the host — every cloud resource is created and removed here, so a re-run is repeatable.
# usage: scripts/oci_lab.sh adb-create <public ip> | wallet | upload | datasafe | status | cleanup | check
#   adb-create  Always Free ADB 26ai "bankadb", mTLS, access list = the given IP only
#   wallet      mTLS wallet -> ../wallet (git-ignored)
#   upload      private bucket bankdb-dump + stage/bankdb_01.dmp (timeouts: an IP change once hung an upload 27 min)
#   datasafe    register the ADB in Data Safe, refresh its security + user assessments, print the counts
#   cleanup     Data Safe assessments (security, user, crypto) + target, ADB, object + bucket, local wallet/stage
#   check       every resource left in the compartment (must be none), IAM policies, cost since 10-28
# Passwords from ../lab.env go into mode-600 JSON files for --from-json (never on a command line) and are
# removed right after. OCIDs stay in stage/ (git-ignored) and are never printed.
# The dynamic group + policy for the ADB's resource principal are created by hand in Cloud Shell (README).
set -eu
H=$(cd "$(dirname "$0")/.." && pwd); S=$H/stage; mkdir -p "$S"; chmod 700 "$S"
O=/home/huy/work/tools/venvs/oci/bin/oci
BUCKET=bankdb-dump
C=$($O search resource structured-search --query-text "query compartment resources where displayName = 'oracle-lab'" \
      --query 'data.items[0].identifier' --raw-output)
[ -n "$C" ] || { echo "compartment oracle-lab not found"; exit 1; }
ADB() { cat "$S/adb.id"; }
# secret_json <file> <python dict expression using env/os.environ>: JSON with a password, mode 600
secret_json() { ( umask 077; set -a; . "$H/lab.env"; set +a; C=$C python3 -I -c "import json, os; e = os.environ; print(json.dumps($2))" > "$1" ); }
ts() { date +%s; }

case ${1:?mode} in
adb-create)
  ip=${2:?public ip}; f=$S/adb-create.json; t0=$(ts)
  IP=$ip secret_json "$f" '{"compartmentId": e["C"], "dbName": "BANKADB", "displayName": "bankadb", "isFreeTier": True,
    "dbVersion": "26ai", "dbWorkload": "OLTP", "isMtlsConnectionRequired": True, "whitelistedIps": [e["IP"]],
    "adminPassword": e["ADB_ADMIN_PASSWORD"]}'
  rc=0; $O db autonomous-database create --from-json "file://$f" --wait-for-state AVAILABLE --max-wait-seconds 1800 \
    --query 'data.id' --raw-output > "$S/adb.id" || rc=$?
  rm -f "$f"
  echo "adb-create rc=$rc in $(( $(ts) - t0 )) s"
  $O db autonomous-database get --autonomous-database-id "$(ADB)" --query 'data.{state:"lifecycle-state",version:"db-version",
    free:"is-free-tier",mtls:"is-mtls-connection-required",acl:"whitelisted-ips",ecpu:"compute-count",storage_gb:"data-storage-size-in-gbs"}' ;;
wallet)
  f=$S/wallet.json
  S=$S secret_json "$f" '{"autonomousDatabaseId": open(e["S"] + "/adb.id").read().strip(), "password": e["ADB_WALLET_PASSWORD"]}'
  rc=0; $O db autonomous-database generate-wallet --from-json "file://$f" --file "$S/wallet.zip" >/dev/null || rc=$?
  rm -f "$f"; [ $rc = 0 ] || { echo "generate-wallet rc=$rc"; exit 1; }
  rm -rf "$H/wallet"; mkdir -m 700 "$H/wallet"; unzip -q -o "$S/wallet.zip" -d "$H/wallet"; rm -f "$S/wallet.zip"
  ls "$H/wallet" | tr '\n' ' '; echo ;;
upload)
  $O os bucket create --compartment-id "$C" --name $BUCKET --public-access-type NoPublicAccess --query 'data.name' --raw-output
  t0=$(ts)
  timeout 900 $O os object put --bucket-name $BUCKET --file "$S/bankdb_01.dmp" --name bankdb_01.dmp --force \
    --part-size 32 --parallel-upload-count 2 --connection-timeout 10 --read-timeout 60 >/dev/null
  echo "upload $(stat -c %s "$S/bankdb_01.dmp") bytes in $(( $(ts) - t0 )) s"
  $O os object list --bucket-name $BUCKET --query 'data[].{name:name,size:size}' --output table ;;
datasafe)
  if [ ! -s "$S/ds.id" ]; then
    printf '{"databaseType":"AUTONOMOUS_DATABASE","infrastructureType":"ORACLE_CLOUD","autonomousDatabaseId":"%s"}' "$(ADB)" > "$S/ds-details.json"
    $O data-safe target-database create --compartment-id "$C" --display-name bankadb --database-details "file://$S/ds-details.json" \
      --wait-for-state SUCCEEDED --wait-for-state FAILED --max-wait-seconds 1200 >/dev/null
    rm -f "$S/ds-details.json"
    $O data-safe target-database list --compartment-id "$C" --display-name bankadb --lifecycle-state ACTIVE \
      --query 'data[0].id' --raw-output > "$S/ds.id"
  fi
  T=$(cat "$S/ds.id"); [ -n "$T" ] || { echo "no Data Safe target"; exit 1; }
  for kind in security-assessment user-assessment; do
    id=$($O data-safe $kind list --compartment-id "$C" --target-id "$T" --type LATEST --query 'data[0].id' --raw-output)
    [ -n "$id" ] || { echo "$kind: no LATEST assessment yet"; continue; }
    $O data-safe $kind refresh --${kind}-id "$id" --wait-for-state SUCCEEDED --max-wait-seconds 1200 >/dev/null || true
    echo "== $kind"
    $O data-safe $kind get --${kind}-id "$id" --query 'data.statistics' --output json
  done ;;
status)
  $O search resource structured-search --query-text "query all resources where compartmentId = '$C' && lifecycleState != 'TERMINATED' && lifecycleState != 'DELETED'" \
    --query 'data.items[].{type:"resource-type",name:"display-name",state:"lifecycle-state"}' --output table ;;
cleanup)
  if [ -s "$S/ds.id" ]; then T=$(cat "$S/ds.id")
    for kind in security-assessment user-assessment; do
      for id in $($O data-safe $kind list --compartment-id "$C" --target-id "$T" --all --query 'data[].id' --raw-output 2>/dev/null | tr -d '[],"'); do
        $O data-safe $kind delete --${kind}-id "$id" --force --wait-for-state SUCCEEDED >/dev/null 2>&1 || echo "$kind delete failed"
      done
    done
    $O data-safe target-database delete --target-database-id "$T" --force --wait-for-state SUCCEEDED >/dev/null && rm -f "$S/ds.id"
  fi
  # Registering a target also creates a crypto assessment and an audit trail; deleting the target leaves both
  # (crypto assessments of runs 1 and 2 were still there 5 days later). Use the Data Safe API, not Resource Search:
  # Search showed other OCIDs for them (get/delete -> NotAuthorizedOrNotFound). Audit profile, audit policy and
  # database security config have no delete (service-managed, they go with the target).
  for k in crypto-assessment audit-trail; do
    for id in $($O data-safe $k list --compartment-id "$C" --all --query 'data.items[].id' --raw-output 2>/dev/null | tr -d '[],"'); do
      $O data-safe $k delete --${k}-id "$id" --force --wait-for-state SUCCEEDED --wait-for-state FAILED >/dev/null 2>&1 || echo "$k delete failed"
    done
  done
  if [ -s "$S/adb.id" ]; then
    for i in 1 2 3; do   # runs 1 and 3: the first delete had no effect (run 3: right after the Data Safe target delete)
      sleep 30
      $O db autonomous-database delete --autonomous-database-id "$(ADB)" --force --wait-for-state TERMINATED --max-wait-seconds 1800 2>&1 \
        | grep -oE '"message": "[^"]*' | head -1 || true
      st=$($O db autonomous-database get --autonomous-database-id "$(ADB)" --query 'data."lifecycle-state"' --raw-output 2>/dev/null || echo GONE)
      echo "ADB: $st"; case $st in TERMINATED|GONE) rm -f "$S/adb.id"; break ;; esac
    done
  fi
  $O os object delete --bucket-name $BUCKET --object-name bankdb_01.dmp --force 2>/dev/null || true
  $O os bucket delete --bucket-name $BUCKET --force 2>/dev/null && echo "bucket deleted" || echo "bucket: not there"
  rm -rf "$H/wallet" "$S/bankdb_01.dmp" ;;
check)
  echo "== resources in compartment oracle-lab (not terminated/deleted)"
  "$0" status
  echo "== IAM policies (tenancy)"
  $O search resource structured-search --query-text "query policy resources" --query 'data.items[].{name:"display-name",state:"lifecycle-state"}' --output table
  echo "== cost since 2026-10-28 by service"
  T=$($O search resource structured-search --query-text "query compartment resources where displayName = 'oracle-lab'" --query 'data.items[0]."compartment-id"' --raw-output)
  $O usage-api usage-summary request-summarized-usages --tenant-id "$T" --time-usage-started 2026-10-28T00:00:00Z \
    --time-usage-ended "$(date -u -d tomorrow +%Y-%m-%dT00:00:00Z)" --granularity MONTHLY --query-type COST --group-by '["service"]' \
    --query 'data.items[].{service:service,cost:"computed-amount",currency:currency}' --output table ;;
*) sed -n '2,12p' "$0"; exit 2 ;;
esac
