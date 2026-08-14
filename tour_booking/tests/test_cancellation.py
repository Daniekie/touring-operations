from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError
from odoo.tools import mute_logger

from .common import TourCase


class TestCancellation(TourCase):
    """The refund is a record of what happened, not a live estimate."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy = cls.env["tour.cancellation.policy"].create({
            "name": "Standard",
            "rule_ids": [
                (0, 0, {"hours_before": 48, "refund_percent": 100.0}),
                (0, 0, {"hours_before": 24, "refund_percent": 50.0}),
            ],
        })
        cls.tour.cancellation_policy_id = cls.policy

    def _paid_booking(self, departure, pax=2):
        """A booking with money actually taken against it.

        Refunds are a percentage of what was paid, not of what was invoiced, so
        a test that never pays would assert nothing.
        """
        booking = self._booking(departure=departure, pax=pax)
        self._transaction(booking, "done")
        booking.action_confirm()
        return booking

    def test_a_booking_keeps_the_policy_it_was_sold_under(self):
        """Editing a policy must never rewrite the terms of a booking already
        sold. The snapshot is the whole point."""
        booking = self._booking(pax=1)
        self.assertEqual(booking.cancellation_policy_id, self.policy)

        self.tour.cancellation_policy_id = self.env["tour.cancellation.policy"].create({
            "name": "Harsher",
            "rule_ids": [(0, 0, {"hours_before": 168, "refund_percent": 10.0})],
        })

        self.assertEqual(
            booking.cancellation_policy_id, self.policy,
            "An existing booking picked up a policy it was never sold under.",
        )

    def test_the_refund_follows_the_policy_window_the_cancellation_falls_in(self):
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=72)
        )
        booking = self._paid_booking(departure)

        booking.action_cancel()

        self.assertEqual(booking.refund_percent, 100.0)
        self.assertEqual(booking.refund_amount, booking.amount_paid)

    def test_a_cancellation_in_a_narrower_window_gets_the_smaller_refund(self):
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=30)
        )
        booking = self._paid_booking(departure)

        booking.action_cancel()

        self.assertEqual(booking.refund_percent, 50.0)
        self.assertEqual(booking.refund_amount, booking.amount_paid / 2)

    def test_a_cancellation_inside_the_no_refund_window_refunds_nothing(self):
        self.tour.booking_cutoff_hours = 0
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=2)
        )
        booking = self._paid_booking(departure)

        booking.action_cancel()

        self.assertEqual(booking.refund_percent, 0.0)
        self.assertEqual(booking.refund_amount, 0.0)

    def test_editing_the_policy_does_not_rewrite_a_refund_already_worked_out(self):
        """The booking keeps the policy record; it has to keep the *terms* too.

        Keeping the policy but reading its windows live means the figure moves
        whenever somebody edits them — months after the guest was told what they
        were getting back, and after the money may already have been sent.
        """
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=72)
        )
        booking = self._paid_booking(departure)
        booking.action_cancel()
        self.assertEqual(booking.refund_percent, 100.0)
        refunded = booking.refund_amount

        self.policy.rule_ids.filtered(lambda r: r.hours_before == 48).refund_percent = 10.0

        self.assertEqual(booking.refund_percent, 100.0)
        self.assertEqual(booking.refund_amount, refunded)

    def test_deleting_the_policys_windows_does_not_erase_a_refund(self):
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=72)
        )
        booking = self._paid_booking(departure)
        booking.action_cancel()
        refunded = booking.refund_amount

        self.policy.rule_ids.unlink()

        self.assertEqual(booking.refund_percent, 100.0)
        self.assertEqual(booking.refund_amount, refunded)

    def test_a_policy_a_booking_was_sold_under_cannot_be_deleted(self):
        """`ondelete='set null'` would take the terms of the sale with it."""
        booking = self._booking(pax=1)
        self.assertEqual(booking.cancellation_policy_id, self.policy)

        # Savepoint and mute for the same reasons as everywhere else a
        # constraint is provoked on purpose: the violation aborts the
        # transaction, and `odoo.sql_db` logs the failing statement at ERROR
        # whether or not the caller was expecting it.
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.policy.unlink()

    def test_no_refund_is_calculated_for_a_booking_that_was_never_cancelled(self):
        booking = self._paid_booking(self._departure())

        self.assertEqual(booking.refund_percent, 0.0)
        self.assertEqual(
            booking.refund_amount, 0.0,
            "A live booking must not carry a refund figure. Storing one "
            "computed from the current time would freeze and then mislead.",
        )

    def test_a_booking_cannot_be_cancelled_once_the_departure_has_run(self):
        """Somebody opening their booking the day after the dive must not be
        able to trigger a refund at all, let alone the full one the widest
        window would hand them."""
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=72)
        )
        booking = self._paid_booking(departure)

        # The boat sails.
        departure.start_datetime = fields.Datetime.now() - timedelta(hours=1)

        with self.assertRaises(
            UserError,
            msg="A booking was cancelled after its departure had already run.",
        ):
            booking.action_cancel()
        self.assertEqual(booking.refund_amount, 0.0)

    def test_the_refund_preview_reflects_the_moment_it_is_asked(self):
        """The 'if you cancel now' figure is a method, not a field: it has to
        move as the departure approaches."""
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=72)
        )
        booking = self._paid_booking(departure)

        full = booking._refund_preview()
        half = booking._refund_preview(
            when=departure.start_datetime - timedelta(hours=30)
        )
        none = booking._refund_preview(
            when=departure.start_datetime - timedelta(hours=2)
        )

        self.assertEqual(full, booking.amount_paid)
        self.assertEqual(half, booking.amount_paid / 2)
        self.assertEqual(none, 0.0)

    def test_a_tour_without_a_cancellation_policy_still_books_and_cancels(self):
        """The policy is optional and must stay optional."""
        self.tour.cancellation_policy_id = False
        departure = self._departure()
        booking = self._booking(departure=departure, pax=2)

        booking.action_cancel()

        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(booking.refund_amount, 0.0)
        self.assertEqual(departure.seats_sold, 0)

    def test_an_unpaid_booking_is_refunded_nothing_however_generous_the_policy(self):
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=72)
        )
        booking = self._booking(departure=departure, pax=2)

        booking.action_cancel()

        self.assertEqual(booking.refund_percent, 100.0)
        self.assertEqual(
            booking.refund_amount, 0.0,
            "Nothing was ever paid, so nothing can be given back.",
        )
