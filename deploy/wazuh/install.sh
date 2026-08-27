#!/bin/sh
# Install the AWDTECH SOC Console integrator on a Wazuh manager.
#
#   sudo ./install.sh --slug acme-corp --secret <secret> \
#        --url https://console.awdtech.co.za --level 7 [--group acme-corp]
#
# --group is required on a SHARED manager and must match the tenant's agent
# group. It is the only thing routing that client's alerts to that client's URL:
# an agent in the wrong group produces correctly signed alerts attributed to the
# wrong client, and the console cannot detect that at ingest.
#
# Idempotent. Re-running replaces this tenant's block, leaving other tenants'
# blocks on a shared manager untouched.
#
# POSIX sh: Wazuh appliances are not guaranteed to have bash.

set -eu

OSSEC_DIR=/var/ossec
CONF="$OSSEC_DIR/etc/ossec.conf"
INTEGRATIONS="$OSSEC_DIR/integrations"
SCRIPT_NAME=custom-awd-console

SLUG=""
SECRET=""
URL=""
LEVEL=7
GROUP=""

die() {
    echo "error: $*" >&2
    exit 1
}

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --slug)   SLUG="${2:-}";   shift 2 ;;
        --secret) SECRET="${2:-}"; shift 2 ;;
        --url)    URL="${2:-}";    shift 2 ;;
        --level)  LEVEL="${2:-}";  shift 2 ;;
        --group)  GROUP="${2:-}";  shift 2 ;;
        -h|--help) usage ;;
        *) die "unknown argument: $1" ;;
    esac
done

[ -n "$SLUG" ]   || die "--slug is required"
[ -n "$SECRET" ] || die "--secret is required"
[ -n "$URL" ]    || die "--url is required"

[ "$(id -u)" -eq 0 ] || die "must run as root"
[ -d "$OSSEC_DIR" ]  || die "$OSSEC_DIR not found - is this a Wazuh manager?"
[ -f "$CONF" ]       || die "$CONF not found"

echo "$SLUG" | grep -Eq '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$' \
    || die "slug must be lowercase letters, digits and hyphens"
echo "$LEVEL" | grep -Eq '^([0-9]|1[0-5])$' \
    || die "--level must be 0-15"

HOOK_URL="${URL%/}/api/v1/ingest/wazuh/$SLUG"
BEGIN="<!-- awdsoc:$SLUG:begin -->"
END="<!-- awdsoc:$SLUG:end -->"

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ -f "$SOURCE_DIR/$SCRIPT_NAME" ] || die "$SCRIPT_NAME not found beside this installer"

# --- 1. the integrator script ------------------------------------------------
install -o root -g wazuh -m 750 "$SOURCE_DIR/$SCRIPT_NAME" "$INTEGRATIONS/$SCRIPT_NAME"
echo "installed $INTEGRATIONS/$SCRIPT_NAME"

# --- 2. back up the config ---------------------------------------------------
BACKUP="$CONF.awdsoc.$(date +%Y%m%d%H%M%S).bak"
cp -p "$CONF" "$BACKUP"
echo "backed up config to $BACKUP"

# --- 3. rewrite this tenant's block ------------------------------------------
GROUP_LINE=""
[ -n "$GROUP" ] && GROUP_LINE="    <group>$GROUP</group>"

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

# Drop any previous block for this slug, then append a fresh one before the final
# </ossec_config>. Other tenants' marker blocks are left alone.
awk -v b="$BEGIN" -v e="$END" '
    index($0, b) { skip = 1 }
    !skip        { print }
    index($0, e) { skip = 0 }
' "$CONF" > "$TMP"

if ! grep -q '</ossec_config>' "$TMP"; then
    die "no </ossec_config> in $CONF - refusing to guess where the block goes"
fi

BLOCK=$(
    printf '%s\n' "  $BEGIN"
    printf '%s\n' "  <integration>"
    printf '%s\n' "    <name>$SCRIPT_NAME</name>"
    printf '%s\n' "    <hook_url>$HOOK_URL</hook_url>"
    printf '%s\n' "    <api_key>$SECRET</api_key>"
    [ -n "$GROUP_LINE" ] && printf '%s\n' "$GROUP_LINE"
    printf '%s\n' "    <level>$LEVEL</level>"
    printf '%s\n' "    <alert_format>json</alert_format>"
    printf '%s\n' "  </integration>"
    printf '%s\n' "  $END"
)

# Insert before the LAST </ossec_config>.
LAST=$(grep -n '</ossec_config>' "$TMP" | tail -1 | cut -d: -f1)
{
    head -n "$((LAST - 1))" "$TMP"
    printf '%s\n' "$BLOCK"
    tail -n "+$LAST" "$TMP"
} > "$CONF.new"

chown --reference="$CONF" "$CONF.new" 2>/dev/null || true
chmod --reference="$CONF" "$CONF.new" 2>/dev/null || chmod 660 "$CONF.new"
mv "$CONF.new" "$CONF"
echo "added integration block for $SLUG${GROUP:+ (group $GROUP)}"

# --- 4. restart, and roll back if it will not come up ------------------------
echo "restarting wazuh-manager..."
if "$OSSEC_DIR/bin/wazuh-control" restart >/dev/null 2>&1; then
    echo "done. alerts at level >= $LEVEL now post to $HOOK_URL"
    if [ -z "$GROUP" ]; then
        echo
        echo "NOTE: no --group given. On a shared manager this sends EVERY alert"
        echo "      on this manager to this tenant. Re-run with --group unless"
        echo "      this manager serves exactly one client."
    fi
else
    echo "manager failed to restart - restoring $BACKUP" >&2
    cp -p "$BACKUP" "$CONF"
    "$OSSEC_DIR/bin/wazuh-control" restart >/dev/null 2>&1 || true
    die "rolled back; check $OSSEC_DIR/logs/ossec.log"
fi
