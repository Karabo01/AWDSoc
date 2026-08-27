#!/bin/sh
# Push one synthetic alert through the installed integrator.
#
#   sudo ./send-test-alert.sh --slug awdtech --secret '<secret>' \
#        [--url https://soc.awdtech.co.za] [--level 10]
#
# This calls /var/ossec/integrations/custom-awd-console exactly the way the Wazuh
# integrator does, so it tests the real path: signing, the replay window, the
# CIDR allowlist, the Redis buffer, the worker, normalisation and grouping. The
# only thing it does not exercise is Wazuh's own decoding and rule matching.
#
# If this lands in the console but real alerts do not, the fault is on the Wazuh
# side - the level floor, the <group> filter, or the rule not firing.
#
# The alert is shaped like rule 5712 (sshd brute force, level 10) because it
# exercises the most machinery: the sshd override in the ECS map, the full_log
# address sweep, entity extraction and MITRE mapping.

set -eu

SLUG=""
SECRET=""
URL="https://soc.awdtech.co.za"
LEVEL=10
INTEGRATOR=/var/ossec/integrations/custom-awd-console

die() {
    echo "error: $*" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --slug)   SLUG="${2:-}";   shift 2 ;;
        --secret) SECRET="${2:-}"; shift 2 ;;
        --url)    URL="${2:-}";    shift 2 ;;
        --level)  LEVEL="${2:-}";  shift 2 ;;
        *) die "unknown argument: $1" ;;
    esac
done

[ -n "$SLUG" ]   || die "--slug is required"
[ -n "$SECRET" ] || die "--secret is required"
[ -f "$INTEGRATOR" ] || die "$INTEGRATOR not found - run install.sh first"

HOOK_URL="${URL%/}/api/v1/ingest/wazuh/$SLUG"

# Unique per run: the console dedupes on (tenant, alert id, timestamp), so a
# repeated id would be silently absorbed and look like a delivery failure.
ALERT_ID="$(date +%s).$$"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%S).000+0000"
SRCIP="${SRCIP:-45.155.205.233}"
AGENT_NAME="$(hostname)"

ALERT_FILE="$(mktemp)"
trap 'rm -f "$ALERT_FILE"' EXIT

cat > "$ALERT_FILE" <<JSON
{
  "timestamp": "$TIMESTAMP",
  "rule": {
    "level": $LEVEL,
    "description": "sshd: brute force trying to get access to the system",
    "id": "5712",
    "firedtimes": 1,
    "mitre": {"id": ["T1110"], "tactic": ["Credential Access"], "technique": ["Brute Force"]},
    "groups": ["syslog", "sshd", "authentication_failures"]
  },
  "agent": {"id": "000", "name": "$AGENT_NAME", "ip": "127.0.0.1"},
  "manager": {"name": "$AGENT_NAME"},
  "id": "$ALERT_ID",
  "decoder": {"name": "sshd"},
  "location": "/var/log/auth.log",
  "full_log": "$(date '+%b %d %H:%M:%S') $AGENT_NAME sshd[4412]: Failed password for invalid user admin from $SRCIP port 40122 ssh2",
  "predecoder": {"hostname": "$AGENT_NAME"},
  "data": {"srcip": "$SRCIP", "srcport": "40122", "srcuser": "admin"}
}
JSON

echo "sending alert id $ALERT_ID (level $LEVEL) to $HOOK_URL"
"$INTEGRATOR" "$ALERT_FILE" "$SECRET" "$HOOK_URL"

echo
echo "sent. the integrator never reports success, so check:"
echo "  tail -n 20 /var/ossec/logs/integrations.log   # a line here names the failure"
echo "  the console overview, or GET /api/v1/ingest/status"
echo
echo "an incident titled 'sshd: brute force...' should appear in the queue."
