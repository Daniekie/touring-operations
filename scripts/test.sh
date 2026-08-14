#!/usr/bin/env bash
#
# Run the tour_booking test suite on a throwaway database.
#
# The test tag is baked in on purpose. A bare `--test-enable` runs the whole
# Odoo core suite, which takes an age and fails for reasons that have nothing
# to do with this module; scoping it here means it cannot be forgotten.
#
#   ./scripts/test.sh                      all tests, both ways (see below)
#   ./scripts/test.sh :TestBooking         one class
#   ./scripts/test.sh :TestBooking.test_x  one test
#
# Mind the colon. A tag Odoo cannot match runs nothing and still exits 0, so a
# mistyped filter looks exactly like a passing suite.
#
# DEMO=with   only the demo-data pass, which is the quick one to iterate on
# DEMO=none   only the no-demo pass
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ODOO="/Users/danique/Github/odoo19"
VENV="$ODOO/.venv/bin/python"

# The suffix lets a caller narrow to a class or a single test, e.g.
# `:TestBooking` or `:TestBooking.test_a_booking_draws_down_the_seats_it_takes`.
TAGS="/tour_booking${1:-}"
DEMO="${DEMO:-both}"

run() {
    local mode="$1" db="tour_test_$1" flag
    # Odoo 19 flipped the default: demo data is no longer loaded unless asked
    # for. Both settings have to be exercised, because both happen for real —
    # a fresh install with demo, and an Odoo.sh development build, which is
    # made from a copy of production and has never had demo data in it. A
    # suite that only ever runs one of them lets tests quietly depend on demo
    # records and fails on the build server instead of here.
    if [ "$mode" = "with" ]; then flag="--with-demo"; else flag="--without-demo=1"; fi

    echo "=== ${mode} demo data ==="
    dropdb --if-exists "$db"
    createdb "$db"
    # A port of its own, so a dev server left running on 8069 does not stop the
    # suite. HttpCase needs a real listening socket, so this cannot just be off.
    "$VENV" "$ODOO/odoo-bin" \
        -c "$REPO/odoo.conf" \
        -d "$db" \
        -i tour_booking \
        --test-enable \
        --test-tags "$TAGS" \
        --stop-after-init \
        --http-port=8079 \
        $flag \
        --log-level=warn
}

case "$DEMO" in
    with) run with ;;
    none) run none ;;
    *)    run with; run none ;;
esac
