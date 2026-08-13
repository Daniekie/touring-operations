from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError

from .common import TourCase


class TestBooking(TourCase):
    """Seats are an inventory that gets drawn down, not a flag that gets set."""

    def test_a_booking_draws_down_the_seats_it_takes(self):
        departure = self._departure(capacity=10)

        self._booking(departure=departure, pax=3)

        self.assertEqual(departure.seats_sold, 3)
        self.assertEqual(departure.seats_available, 7)

    def test_several_bookings_share_one_departure(self):
        """The whole point of the model: a departure is shared, not exclusive."""
        departure = self._departure(capacity=10)

        self._booking(departure=departure, pax=4)
        self._booking(departure=departure, pax=6, partner=self.other_partner)

        self.assertEqual(departure.seats_sold, 10)
        self.assertEqual(departure.state, "full")

    def test_a_booking_cannot_exceed_remaining_seats(self):
        departure = self._departure(capacity=5)
        self._booking(departure=departure, pax=4)

        with self.assertRaises(UserError, msg="A sixth seat was sold on a boat of five."):
            self._booking(departure=departure, pax=2, partner=self.other_partner)

        self.assertEqual(departure.seats_sold, 4)

    def test_a_departure_becomes_full_when_the_last_seat_sells(self):
        departure = self._departure(capacity=4)

        self._booking(departure=departure, pax=4)

        self.assertEqual(departure.state, "full")
        self.assertEqual(departure.seats_available, 0)
        self.assertFalse(
            departure.is_manually_adjusted,
            "Selling out is bookkeeping. Flagging it as a manual adjustment "
            "would exempt the departure from ever being retired.",
        )

    def test_a_cancelled_booking_returns_its_seats(self):
        departure = self._departure(capacity=4)
        booking = self._booking(departure=departure, pax=4)
        self.assertEqual(departure.state, "full")

        booking.action_cancel()

        self.assertEqual(departure.seats_sold, 0)
        self.assertEqual(departure.seats_available, 4)
        self.assertEqual(departure.state, "open", "A freed seat should be back on sale.")

    def test_a_draft_booking_holds_its_seats(self):
        """A draft is a checkout in flight. If it did not hold its seats, two
        guests could both pay for the same last place."""
        departure = self._departure(capacity=2)
        booking = self._booking(departure=departure, pax=2)
        self.assertEqual(booking.state, "draft")

        self.assertEqual(departure.seats_available, 0)
        with self.assertRaises(UserError):
            self._booking(departure=departure, pax=1, partner=self.other_partner)

    def test_bookings_are_refused_after_the_cutoff(self):
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=12)
        )

        with self.assertRaises(
            UserError,
            msg="A booking was accepted inside the 24-hour cut-off.",
        ):
            self._booking(departure=departure, pax=1)

    def test_bookings_are_accepted_right_up_to_the_cutoff(self):
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(hours=25)
        )

        booking = self._booking(departure=departure, pax=1)

        self.assertTrue(booking, "A booking just outside the cut-off was refused.")

    def test_a_tour_without_a_cutoff_takes_bookings_until_departure(self):
        self.tour.booking_cutoff_hours = 0
        departure = self._departure(
            start_datetime=fields.Datetime.now() + timedelta(minutes=5)
        )

        self.assertTrue(self._booking(departure=departure, pax=1))

    def test_a_booking_must_respect_the_party_size_limits(self):
        """min_pax and max_pax limit one booking's party size.

        They are not a viability threshold: min_pax does not mean the departure
        only runs once that many people have booked in total.
        """
        departure = self._departure(capacity=20, min_pax=2, max_pax=6)

        with self.assertRaises(ValidationError, msg="A party below the minimum was accepted."):
            self._booking(departure=departure, pax=1)
        with self.assertRaises(ValidationError, msg="A party above the maximum was accepted."):
            self._booking(departure=departure, pax=7, partner=self.other_partner)

        self.assertTrue(self._booking(departure=departure, pax=2))

    def test_many_small_bookings_fill_a_departure_with_a_minimum_party_size(self):
        """Six bookings of two are a full boat, not a failed minimum."""
        departure = self._departure(capacity=12, min_pax=2, max_pax=6)

        for _ in range(6):
            partner = self.env["res.partner"].create({"name": "Guest"})
            self._booking(departure=departure, pax=2, partner=partner)

        self.assertEqual(departure.seats_sold, 12)
        self.assertEqual(departure.state, "full")

    def test_growing_a_booking_only_asks_for_the_extra_seats(self):
        departure = self._departure(capacity=5)
        booking = self._booking(departure=departure, pax=4)

        booking.pax = 5

        self.assertEqual(departure.seats_sold, 5)

    def test_growing_a_booking_past_capacity_is_refused(self):
        departure = self._departure(capacity=5)
        booking = self._booking(departure=departure, pax=4)

        with self.assertRaises(UserError):
            booking.pax = 6

    def test_a_booking_on_a_cancelled_departure_is_refused(self):
        departure = self._departure()
        departure.action_cancel()

        with self.assertRaises(UserError):
            self._booking(departure=departure, pax=1)

    def test_a_cancelled_booking_cannot_be_confirmed(self):
        booking = self._booking(pax=1)
        booking.action_cancel()

        with self.assertRaises(UserError):
            booking.action_confirm()

    def test_confirming_does_not_count_the_bookings_own_seats_against_it(self):
        """The seats were taken at creation and are held by this very booking.

        Re-checking capacity at confirmation would count them against
        themselves, and every booking that sold the last seat would then be
        impossible to confirm.
        """
        departure = self._departure(capacity=3)
        booking = self._booking(departure=departure, pax=3)

        booking.action_confirm()

        self.assertEqual(booking.state, "confirmed")
        self.assertEqual(departure.seats_sold, 3)

    def test_a_booking_gets_a_reference_and_an_access_token(self):
        booking = self._booking(pax=1)

        self.assertTrue(booking.name.startswith("TOUR/"))
        self.assertTrue(booking._portal_ensure_token())
