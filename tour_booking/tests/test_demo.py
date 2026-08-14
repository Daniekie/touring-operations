"""The demo database, and the message a fresh one shows.

Demo data is not decoration here: it is the only thing standing between a new
install and a screen full of nothing, and it is loaded by the test run itself
(`--with-demo`), so it may as well be asserted rather than assumed.
"""

from .common import TourCase


class TestDemoData(TourCase):

    def _demo(self, xmlid):
        return self.env.ref("tour_booking.%s" % xmlid)

    def test_the_demo_database_ships_with_confirmed_bookings(self):
        """Seats sold on real generated departures, not fixtures in isolation."""
        guest = self._demo("demo_partner_hartman")
        booking = self.env["tour.booking"].search([("partner_id", "=", guest.id)])

        self.assertEqual(len(booking), 1)
        self.assertEqual(booking.state, "confirmed")
        self.assertEqual(booking.tour_id, self._demo("demo_tour_sunset"))
        self.assertTrue(
            booking.departure_id.seats_sold >= booking.pax,
            "A demo booking has to draw down the departure it sits on.",
        )

    def test_a_demo_booking_that_needed_answers_still_confirmed(self):
        """The scuba trip asks two required questions of every diver, and
        `action_confirm` refuses without them — so this is the demo record most
        likely to end up silently stuck in draft."""
        guest = self._demo("demo_partner_lindqvist")
        booking = self.env["tour.booking"].search([("partner_id", "=", guest.id)])

        self.assertEqual(booking.state, "confirmed")
        self.assertEqual(len(booking.answer_ids), 5)

    def test_a_demo_booking_is_cancelled_so_a_refund_is_visible(self):
        guest = self._demo("demo_partner_tanaka")
        booking = self.env["tour.booking"].search([("partner_id", "=", guest.id)])

        self.assertEqual(booking.state, "cancelled")
        self.assertTrue(booking.cancelled_on)

    def test_seeding_twice_does_not_double_the_demo_bookings(self):
        """`<function>` in a demo file fires again on every module upgrade."""
        before = self.env["tour.booking"].search_count([])

        self.env["tour.booking"]._demo_create_bookings()

        self.assertEqual(self.env["tour.booking"].search_count([]), before)

    def test_the_empty_state_points_at_creating_an_experience(self):
        """The first screen of a fresh install.

        "No bookings yet" is true and useless on day one: nothing can be booked
        until something is on sale, and nothing on this screen says so.
        """
        self.env["tour.tour"].search([]).action_archive()

        help_text = self.env["tour.booking"].get_empty_list_help("No bookings yet")

        self.assertIn("Create new Experience", help_text)

    def test_the_empty_state_is_the_ordinary_one_once_a_tour_exists(self):
        help_text = self.env["tour.booking"].get_empty_list_help("No bookings yet")

        self.assertEqual(help_text, "No bookings yet")
