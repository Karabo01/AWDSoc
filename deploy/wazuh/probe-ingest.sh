#!/bin/sh
# Send one signed alert and SHOW THE HTTP RESPONSE.
#
#   sudo ./probe-ingest.sh --slug awdtech --secret '<secret>' \
#        [--url https://soc.awdtech.co.za]
#
# The integrator is built to never block and never raise, so it swallows every
# failure and exits 0. That is correct in production - a fork-per-alert script
# that crashes is worse than one that gives up quietly - but it means a
# misconfigured tenant is silent at both ends. This does the same signing by
# hand and prints exactly what the console said.
#
# Reading the result:
#   202  accepted. The fault is downstream: worker, database, or grouping.
#   401  rejected. One of: wrong secret, clock skew over 300s, source address
#        not in ingest_cidrs, or the slug does not exist. The console will not
#        say which - by design, so the endpoint cannot enumerate tenants - but
#        the api container's logs name the reason.
#   429  rate limited for this tenant.
#   503  the console cannot verify the tenant right now (database degraded).
#   404  the request never reached the ingest route: check the URL and whether
#        the proxy is rewriting the path.

set -eu

SLUG=""
SECRET=""
URL="https://soc.awdtech.co.za"

die() {
    echo "error: $*" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --slug)   SLUG="${2:-}";   shift 2 ;;
        --secret) SECRET="${2:-}"; shift 2 ;;
        --url)    URL="${2:-}";    shift 2 ;;
        *) die "unknown argument: $1" ;;
    esac
done

[ -n "$SLUG" ]   || die "--slug is required"
[ -n "$SECRET" ] || die "--secret is required"
command -v openssl >/dev/null || die "openssl is required"
command -v curl >/dev/null    || die "curl is required"

HOOK_URL="${URL%/}/api/v1/ingest/wazuh/$SLUG"
ID="$(date +%s).$$"
TS="$(date -u +%Y-%m-%dT%H:%M:%S).000+0000"
H="$(hostname)"

# Compact, no spaces - the console verifies the exact bytes it receives, so the
# body signed here must be the body sent, byte for byte.
BODY='{"timestamp":"'"$TS"'","id":"'"$ID"'","rule":{"level":10,"id":"5712","description":"probe: ingest connectivity test","groups":["syslog","sshd","authentication_failures"]},"agent":{"id":"000","name":"'"$H"'","ip":"127.0.0.1"},"location":"/var/log/auth.log","full_log":"probe from '"$H"'","data":{"srcip":"45.155.205.233","srcuser":"probe"}}'

UNIX_TS="$(date +%s)"
SIG="$(printf '%s.%s' "$UNIX_TS" "$BODY" \
    | openssl dgst -sha256 -hmac "$SECRET" -r | cut -d' ' -f1)"

echo "POST $HOOK_URL"
echo "  alert id  : $ID"
echo "  timestamp : $UNIX_TS ($(date -u))"
echo "  egress ip : $(curl -s --max-time 5 https://ifconfig.me || echo '(could not determine)')"
echo

curl -sS -i --max-time 15 -X POST "$HOOK_URL" \
    -H "Content-Type: application/json" \
    -H "X-AWD-Timestamp: $UNIX_TS" \
    -H "X-AWD-Signature: sha256=$SIG" \
    --data-raw "$BODY"

echo
echo
echo "If this returned 401, compare the egress ip above against the client's"
echo "ingest_cidrs in the console, and check both clocks are within 300s."
