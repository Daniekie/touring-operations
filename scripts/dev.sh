#!/usr/bin/env bash
#
# Start Odoo on http://localhost:8069 against a persistent development
# database, so the back office and the website can be clicked through.
#
# `--dev=reload,qweb,xml` means Python changes restart the server and XML and
# QWeb changes take effect on reload, without an explicit module upgrade.
#
#   ./scripts/dev.sh          start the server
#   ./scripts/dev.sh -u       start it and upgrade tour_booking first
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ODOO="/Users/danique/Github/odoo19"
VENV="$ODOO/.venv/bin/python"
DB="tour_dev"

if ! psql -lqt | cut -d'|' -f1 | grep -qw "$DB"; then
    echo "Creating $DB and installing tour_booking..."
    createdb "$DB"
    "$VENV" "$ODOO/odoo-bin" -c "$REPO/odoo.conf" -d "$DB" \
        -i tour_booking --stop-after-init --log-level=warn
fi

# macOS ships bash 3.2, where `set -u` treats an empty array expansion as an
# unbound variable. Passing the flag as a plain string sidesteps that entirely.
UPGRADE=""
[[ "${1:-}" == "-u" ]] && UPGRADE="-u tour_booking"

exec "$VENV" "$ODOO/odoo-bin" \
    -c "$REPO/odoo.conf" \
    -d "$DB" \
    --dev=reload,qweb,xml \
    $UPGRADE
