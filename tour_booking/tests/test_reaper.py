from datetime import timedelta

from odoo import fields

from odoo.addons.tour_booking.models import tour_booking

from .common import TourCase


class TestReaper(TourCase):
    """Abandoned checkouts must give their seats back — but only the genuinely
    abandoned ones."""

    def _age(self, booking, minutes):
        """Backdate a booking past the reaper's cutoff.

        `create_date` is not writable through the ORM, so this goes straight to
        SQL. The alternative is a test that sleeps for half an hour.
        """
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE tour_booking SET create_date = %s WHERE id = %s",
            [fields.Datetime.now() - timedelta(minutes=minutes), booking.id],
        )
        booking.invalidate_recordset(["create_date"])

    def test_the_reaper_releases_a_draft_that_never_started_paying(self):
        departure = self._departure(capacity=4)
        booking = self._booking(departure=departure, pax=4)
        self._age(booking, 45)

        self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(departure.seats_available, 4, "The seats went back on sale.")

    def test_the_reaper_works_in_bounded_batches(self):
        """It ran `search()` with no limit and then loaded every stale draft's
        transactions into memory.

        On a quiet database that is nothing. After an outage, or a bot that
        spent a night opening checkouts, it is one enormous transaction holding
        row locks on the whole backlog — during trading hours, because it runs
        every fifteen minutes. A run that takes a fixed bite and leaves the rest
        for the next one has no such worst case.
        """
        # The batch size is patched rather than honoured: the behaviour under
        # test is "takes a fixed bite and leaves the rest", and asserting it at
        # the production size would mean two hundred bookings and the seats to
        # put them on.
        self.patch(tour_booking, "REAPER_BATCH", 3)
        departure = self._departure(capacity=10)
        stale = self.env["tour.booking"]
        for _ in range(5):
            booking = self._booking(departure=departure, pax=1)
            self._age(booking, 45)
            stale |= booking

        first = self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertEqual(len(first), 3)
        self.assertEqual(len(stale.filtered(lambda b: b.state == "draft")), 2)

        second = self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertEqual(len(second), 2, "The rest were never picked up.")
        self.assertFalse(stale.filtered(lambda b: b.state == "draft"))

    def test_the_reaper_leaves_a_recent_draft_alone(self):
        booking = self._booking(pax=2)

        self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertEqual(booking.state, "draft")

    def test_the_reaper_leaves_a_draft_whose_payment_is_still_pending(self):
        """The bug this test exists for: an iDEAL payment or a bank transfer can
        settle at minute 35. A reaper going purely on the clock would already
        have resold those seats, and the provider's callback would then confirm
        a booking against capacity that no longer exists."""
        departure = self._departure(capacity=4)
        booking = self._booking(departure=departure, pax=4)
        self._transaction(booking, "pending")
        self._age(booking, 45)

        self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertEqual(
            booking.state, "draft",
            "A draft with a payment still in flight was reaped, and its seats "
            "can now be sold to somebody else.",
        )
        self.assertEqual(departure.seats_available, 0)

    def test_the_reaper_leaves_a_draft_whose_payment_is_authorized(self):
        booking = self._booking(pax=2)
        self._transaction(booking, "authorized")
        self._age(booking, 45)

        self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertEqual(booking.state, "draft")

    def test_the_reaper_leaves_a_draft_whose_payment_already_succeeded(self):
        """A done transaction on a still-draft booking means post-processing has
        not caught up. Reaping it would cancel a booking that has been paid."""
        booking = self._booking(pax=2)
        self._transaction(booking, "done")
        self._age(booking, 45)

        self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertEqual(booking.state, "draft")

    def test_the_reaper_releases_a_draft_whose_payment_failed(self):
        departure = self._departure(capacity=4)
        booking = self._booking(departure=departure, pax=4)
        self._transaction(booking, "error")
        self._age(booking, 45)

        self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(departure.seats_available, 4)

    def test_a_reaped_draft_carries_no_refund(self):
        """Nobody cancelled it and nobody paid for it, so there is nothing to
        give back and no cancellation date to record."""
        booking = self._booking(pax=2)
        self._age(booking, 45)

        self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertFalse(booking.cancelled_on)
        self.assertEqual(booking.refund_amount, 0.0)

    def test_the_reaper_never_touches_a_confirmed_booking(self):
        booking = self._booking(pax=2)
        booking.action_confirm()
        self._age(booking, 500)

        self.env["tour.booking"]._cron_release_abandoned_drafts()

        self.assertEqual(booking.state, "confirmed")
