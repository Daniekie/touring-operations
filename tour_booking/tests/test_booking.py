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

    def test_a_batch_of_bookings_cannot_oversell_one_departure(self):
        """One `create()` call, several bookings, the same boat.

        Checking each set of values on its own compares every one of them
        against the same untouched seat count — none of them has been written
        yet — so two parties of four both pass on a boat with six seats left.
        The check has to be made once per departure, for what the whole batch
        is asking for.
        """
        departure = self._departure(capacity=6)

        with self.assertRaises(UserError, msg="A batch of two fours filled a boat of six."):
            self.env["tour.booking"].create([
                {"departure_id": departure.id, "partner_id": self.partner.id, "pax": 4},
                {"departure_id": departure.id,
                 "partner_id": self.other_partner.id, "pax": 4},
            ])

        self.assertEqual(departure.seats_sold, 0)

    def test_a_batch_that_fits_is_still_created(self):
        """The batch is refused for asking too much, not for being a batch."""
        departure = self._departure(capacity=6)

        bookings = self.env["tour.booking"].create([
            {"departure_id": departure.id, "partner_id": self.partner.id, "pax": 4},
            {"departure_id": departure.id, "partner_id": self.other_partner.id, "pax": 2},
        ])

        self.assertEqual(len(bookings), 2)
        self.assertEqual(departure.seats_sold, 6)
        self.assertEqual(departure.state, "full")

    def test_a_batch_across_departures_is_checked_departure_by_departure(self):
        """Seats on one boat are no reason to refuse a seat on another."""
        first = self._departure(capacity=4)
        second = self._departure(
            capacity=4, start_datetime=fields.Datetime.now() + timedelta(days=31)
        )

        bookings = self.env["tour.booking"].create([
            {"departure_id": first.id, "partner_id": self.partner.id, "pax": 4},
            {"departure_id": second.id, "partner_id": self.other_partner.id, "pax": 4},
        ])

        self.assertEqual(len(bookings), 2)
        self.assertEqual(first.seats_sold, 4)
        self.assertEqual(second.seats_sold, 4)

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

    def test_growing_two_bookings_at_once_cannot_oversell(self):
        """One `write()`, several bookings, the same boat.

        Each booking's own seats are handed back to it — that is what `ignoring`
        is for — but handing them back one booking at a time compares each
        growth against a boat the others have not grown on yet. A list-view
        multi-edit then oversells without a word.
        """
        # `max_pax` high enough that seven is a capacity question and not a
        # party-size one — `ValidationError` is a `UserError`, so a party-size
        # refusal would pass this test without capacity ever being consulted.
        departure = self._departure(capacity=10, max_pax=10)
        first = self._booking(departure=departure, pax=2)
        second = self._booking(departure=departure, pax=2, partner=self.other_partner)

        with self.assertRaises(UserError, msg="Two parties of seven fit a boat of ten."):
            (first | second).write({"pax": 7})

        self.assertEqual(departure.seats_sold, 4)

    def test_growing_two_bookings_at_once_is_allowed_when_they_fit(self):
        departure = self._departure(capacity=10)
        first = self._booking(departure=departure, pax=2)
        second = self._booking(departure=departure, pax=2, partner=self.other_partner)

        (first | second).write({"pax": 5})

        self.assertEqual(departure.seats_sold, 10)
        self.assertEqual(departure.state, "full")

    def test_moving_two_bookings_onto_one_departure_is_checked_together(self):
        """The seats they hold on the boat they are leaving are no help on the
        boat they are joining."""
        origin = self._departure(capacity=10)
        target = self._departure(
            capacity=3, start_datetime=fields.Datetime.now() + timedelta(days=31)
        )
        first = self._booking(departure=origin, pax=2)
        second = self._booking(departure=origin, pax=2, partner=self.other_partner)

        with self.assertRaises(UserError, msg="Four people moved onto a boat of three."):
            (first | second).write({"departure_id": target.id})

        self.assertEqual(target.seats_sold, 0)
        self.assertEqual(origin.seats_sold, 4)

    def test_reviving_a_cancelled_booking_is_refused_when_the_seats_have_gone(self):
        """A cancelled booking holds nothing, so putting it back is asking for
        its seats again — on a boat that has since sold them to somebody else.

        The seat check used to run only when `pax` or the departure changed, so
        a state change from the list view walked straight past it.
        """
        departure = self._departure(capacity=4)
        booking = self._booking(departure=departure, pax=4)
        booking.action_cancel()
        self._booking(departure=departure, pax=4, partner=self.other_partner)

        with self.assertRaises(UserError, msg="A cancelled booking took seats already resold."):
            booking.state = "draft"

        self.assertEqual(departure.seats_sold, 4)

    def test_reviving_a_cancelled_booking_is_allowed_when_the_seats_are_there(self):
        departure = self._departure(capacity=10)
        booking = self._booking(departure=departure, pax=4)
        booking.action_cancel()

        booking.state = "draft"

        self.assertEqual(departure.seats_sold, 4)

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
