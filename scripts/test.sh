#!/usr/bin/env bash
#
# Run the tour_booking test suite on a throwaway database.
#
# The test tag is baked in on purpose. A bare `--test-enable` runs the whole
# Odoo core suite, which takes an age and fails for reasons that have nothing
# to do with this module; scoping it here means it cannot be forgotten.
#
#   ./scripts/test.sh                 all tests in the module
#   ./scripts/test.sh .TestBooking    one class
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ODOO="/Users/danique/Github/odoo19"
VENV="$ODOO/.venv/bin/python"
DB="tour_test"

# The suffix lets a caller narrow to a class or a single test, e.g.
# `.TestBooking` or `.TestBooking.test_a_booking_draws_down_the_seats_it_takes`.
TAGS="/tour_booking${1:-}"

dropdb --if-exists "$DB"
createdb "$DB"

# A port of its own, so a dev server left running on 8069 does not stop the
# suite. HttpCase needs a real listening socket, so this cannot just be off.
#
# `--with-demo` because Odoo 19 flipped the default: demo data is no longer
# loaded unless asked for. Without it the demo XML is never parsed here, and a
# broken demo file would sail through a green suite and fail the build instead.
"$VENV" "$ODOO/odoo-bin" \
    -c "$REPO/odoo.conf" \
    -d "$DB" \
    -i tour_booking \
    --test-enable \
    --test-tags "$TAGS" \
    --stop-after-init \
    --http-port=8079 \
    --with-demo \
    --log-level=warn
