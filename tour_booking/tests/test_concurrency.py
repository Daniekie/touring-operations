"""Two guests booking the last seats at the same moment.

This is the awkward test, because the obvious way to write it does not work and
*appears* to.

`registry.cursor()` cannot be used. Inside a test the registry is in test mode
and hands out `odoo.tests.test_cursor.TestCursor` objects: they all sit on one
real connection, they take a mutex when constructed, and their `commit()` is a
`RELEASE SAVEPOINT` rather than a commit. Two of them can never be concurrent by
construction, nothing one writes is visible to the other, and the second blocks
on the mutex — which looks exactly like blocking on a row lock. A test built on
them reports that the locking works even when there is no locking at all.

So this module opens genuinely independent connections with `db_connect` and
commits its fixtures for real, cleaning them up afterwards.

There are also no threads. Contention is provoked with `NOWAIT` and
`lock_timeout`, so Postgres answers immediately and deterministically instead of
the test inferring an answer from how long something took. Nothing here can
hang, and there is no timing constant to tune on a slow machine.
"""

from datetime import timedelta

import psycopg2

from odoo import SUPERUSER_ID, api, fields
from odoo.exceptions import UserError
from odoo.sql_db import db_connect
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

# How long the second transaction waits before giving up on the row lock. It is
# only ever reached when the lock is genuinely held, so it costs nothing in the
# passing case: a bound on failure, not a delay in success.
LOCK_TIMEOUT_MS = 2000


@tagged("post_install", "-at_install")
class TestConcurrentBooking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dbname = cls.env.cr.dbname
        cls.fixtures = cls._create_committed_fixtures()
        cls.addClassCleanup(cls._drop_committed_fixtures)

    def setUp(self):
        """Give each test its own departure, and take it away afterwards.

        These tests commit for real, so anything they write outlives the test
        that wrote it. Sharing one departure across the class would mean the
        seats sold by whichever test ran first are still gone when the next one
        starts — and the failure surfaces as a capacity error in an unrelated
        test rather than as the pollution it actually is.
        """
        super().setUp()
        self.departure_id = self._create_committed_departure()
        self.addCleanup(self._drop_departure, self.departure_id)

    @classmethod
    def _create_committed_departure(cls, capacity=3, offset_days=30):
        cr = cls._real_cursor()
        try:
            env = cls._real_env(cr)
            departure = env["tour.departure"].create({
                "tour_id": cls.fixtures["tour"],
                "date": fields.Date.today() + timedelta(days=offset_days),
                "start_datetime": fields.Datetime.now() + timedelta(days=offset_days),
                "capacity": capacity,
                "min_pax": 1,
                "max_pax": capacity,
            })
            cr.commit()
            return departure.id
        finally:
            cr.close()

    @classmethod
    def _drop_departure(cls, departure_id):
        cr = cls._real_cursor()
        try:
            env = cls._real_env(cr)
            env["tour.booking"].search([("departure_id", "=", departure_id)]).unlink()
            env["tour.departure"].browse(departure_id).unlink()
            cr.commit()
        finally:
            cr.close()

    # --- Real connections --------------------------------------------------

    @classmethod
    def _real_cursor(cls):
        """A cursor on its own database connection.

        Deliberately not `registry.cursor()`; see the module docstring for why
        that would quietly invalidate every assertion in this file.
        """
        return db_connect(cls.dbname).cursor()

    @classmethod
    def _real_env(cls, cr):
        return api.Environment(cr, SUPERUSER_ID, {})

    @classmethod
    def _create_committed_fixtures(cls):
        """The tour, a spare departure for the scope test, and two guests.

        The departure the tests actually fight over is made per-test in setUp.
        """
        cr = cls._real_cursor()
        try:
            env = cls._real_env(cr)
            tour = env["tour.tour"].create({
                "name": "Concurrency Test Dive",
                "duration_hours": 2.0,
                "default_capacity": 3,
                "booking_cutoff_hours": 0,
                "tz": "UTC",
                "price_per_person": 10.0,
                "start_time_ids": [(0, 0, {"time_of_day": 9.0})],
            })
            other = env["tour.departure"].create({
                "tour_id": tour.id,
                "date": fields.Date.today() + timedelta(days=31),
                "start_datetime": fields.Datetime.now() + timedelta(days=31),
                "capacity": 3,
                "min_pax": 1,
                "max_pax": 3,
            })
            partners = env["res.partner"].create([
                {"name": "Concurrency Guest 1"},
                {"name": "Concurrency Guest 2"},
            ])
            cr.commit()
            return {
                "tour": tour.id,
                "other_departure": other.id,
                "partners": partners.ids,
            }
        finally:
            cr.close()

    @classmethod
    def _drop_committed_fixtures(cls):
        """Remove everything this class committed, whatever the tests did."""
        ids = cls.fixtures
        cr = cls._real_cursor()
        try:
            env = cls._real_env(cr)
            env["tour.booking"].search([("tour_id", "=", ids["tour"])]).unlink()
            env["tour.departure"].search([("tour_id", "=", ids["tour"])]).unlink()
            env["tour.tour"].browse(ids["tour"]).unlink()
            env["res.partner"].browse(ids["partners"]).unlink()
            cr.commit()
        finally:
            cr.close()

    # --- Helpers -----------------------------------------------------------

    def _book(self, env, partner_id, pax, departure_id=None):
        return env["tour.booking"].create({
            "departure_id": departure_id or self.departure_id,
            "partner_id": partner_id,
            "pax": pax,
        })

    def _try_lock_nowait(self, cr, departure_id):
        """Attempt the row lock without waiting. -> True if acquired.

        Muted because a refused lock is the expected result here, and
        `odoo.sql_db` logs every failing query at ERROR level whether or not the
        caller handles it.
        """
        with mute_logger("odoo.sql_db"):
            try:
                cr.execute(
                    "SELECT id FROM tour_departure WHERE id = %s FOR UPDATE NOWAIT",
                    [departure_id],
                )
                return True
            except psycopg2.OperationalError:
                # 55P03 lock_not_available: somebody else holds it right now.
                return False

    # --- The lock ----------------------------------------------------------

    def test_the_departure_lock_is_a_real_row_lock(self):
        """A second connection cannot take the lock while the first holds it.

        `NOWAIT` makes Postgres answer at once, so this asserts the lock exists
        rather than inferring it from a wait that might have any number of other
        causes.
        """
        holder = self._real_cursor()
        contender = self._real_cursor()
        try:
            env = self._real_env(holder)
            departure = env["tour.departure"].browse(self.departure_id)
            departure._lock_and_check(1)

            self.assertFalse(
                self._try_lock_nowait(contender, self.departure_id),
                "A second connection took the lock while the first still held "
                "it. Without a real row lock, the last seats can be sold twice.",
            )
            contender.rollback()

            holder.rollback()
            self.assertTrue(
                self._try_lock_nowait(contender, self.departure_id),
                "The lock was not released when the first transaction ended.",
            )
        finally:
            contender.close()
            holder.close()

    def test_the_departure_lock_does_not_block_other_departures(self):
        """Locking one departure must not freeze the whole schedule.

        Worth pinning down: the lazy over-broad implementation — locking the
        table — would pass the test above while serialising every booking the
        business takes.
        """
        holder = self._real_cursor()
        other = self._real_cursor()
        try:
            env = self._real_env(holder)
            env["tour.departure"].browse(self.departure_id)._lock_and_check(1)

            self.assertTrue(
                self._try_lock_nowait(other, self.fixtures["other_departure"]),
                "Locking one departure blocked another; the lock is too broad.",
            )
            other.rollback()
        finally:
            other.close()
            holder.close()

    # --- Two guests, three seats ------------------------------------------

    def test_the_last_seats_cannot_be_sold_twice_under_concurrent_attempts(self):
        """The guarantee, end to end.

        While one transaction is booking, a second cannot get past the seat
        check; once the first commits, the second correctly finds nothing free.
        Between them those two facts are what make overselling impossible — a
        check that ran before the lock, or a lock taken after the check, would
        fail one or the other.
        """
        first = self._real_cursor()
        second = self._real_cursor()
        try:
            env_first = self._real_env(first)
            booking_first = self._book(env_first, self.fixtures["partners"][0], 3)
            self.assertTrue(booking_first)

            # The second transaction runs against a database where the first
            # booking is not yet visible. Only the lock stops it.
            env_second = self._real_env(second)
            second.execute("SET LOCAL lock_timeout = %s", ["%dms" % LOCK_TIMEOUT_MS])
            with mute_logger("odoo.sql_db"), self.assertRaises(
                psycopg2.OperationalError,
                msg="The second booking walked straight past the lock held by "
                    "the first, which is how the last seat gets sold twice.",
            ):
                self._book(env_second, self.fixtures["partners"][1], 3)
            second.rollback()

            # The first commits; the seats are now genuinely gone.
            first.commit()

            retry = self._real_cursor()
            try:
                env_retry = self._real_env(retry)
                with self.assertRaises(
                    UserError,
                    msg="Once the first booking is committed, the second must "
                        "be refused for lack of seats.",
                ):
                    self._book(env_retry, self.fixtures["partners"][1], 3)
                retry.rollback()
            finally:
                retry.close()

            # And the departure never went over capacity.
            check = self._real_cursor()
            try:
                check.execute(
                    "SELECT COALESCE(SUM(pax), 0) FROM tour_booking "
                    "WHERE departure_id = %s AND state IN ('draft', 'confirmed')",
                    [self.departure_id],
                )
                self.assertEqual(
                    check.fetchone()[0], 3,
                    "More seats are sold than the departure has.",
                )
            finally:
                check.close()
        finally:
            second.close()
            first.close()

    def test_a_partial_overlap_is_refused_rather_than_oversold(self):
        """Two guests want two seats each on a boat with three left.

        The interesting case: neither request is impossible on its own, and a
        naive implementation lets both through and carries five people on a boat
        licensed for three.
        """
        first = self._real_cursor()
        second = self._real_cursor()
        try:
            self._book(self._real_env(first), self.fixtures["partners"][0], 2)
            first.commit()

            env_second = self._real_env(second)
            with self.assertRaises(
                UserError,
                msg="Two bookings of two were both accepted on three seats.",
            ):
                self._book(env_second, self.fixtures["partners"][1], 2)
            second.rollback()

            check = self._real_cursor()
            try:
                check.execute(
                    "SELECT COALESCE(SUM(pax), 0) FROM tour_booking "
                    "WHERE departure_id = %s AND state IN ('draft', 'confirmed')",
                    [self.departure_id],
                )
                self.assertLessEqual(check.fetchone()[0], 3)
            finally:
                check.close()
        finally:
            second.close()
            first.close()
