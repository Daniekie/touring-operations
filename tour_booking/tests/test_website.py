import base64
import re

from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import HttpCase

from .common import TourCase

# A 1x1 GIF. The gallery test is about whether images are rendered at all, not
# about what is in them, so the smallest valid image does the job.
IMAGE = base64.b64encode(
    base64.b64decode("R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==")
)


@tagged("post_install", "-at_install")
class TestWebsite(HttpCase, TourCase):
    """The two public pages, and the JSON the booking widget runs on."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tour.is_published = True
        cls.departure = cls.env["tour.departure"].create({
            "tour_id": cls.tour.id,
            "date": fields.Date.today() + timedelta(days=10),
            "start_datetime": fields.Datetime.now() + timedelta(days=10),
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        })

    # --- The catalogue -----------------------------------------------------

    def test_the_tours_page_lists_published_tours_two_to_a_row(self):
        response = self.url_open("/tours")

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("Blue Hole Dive", body)
        self.assertIn(
            "col-md-6", body,
            "The grid must be two cards per row, not full-width rows.",
        )

    def test_a_tour_card_shows_its_duration_price_and_more_info_button(self):
        body = self.url_open("/tours").text

        self.assertIn("3h", body, "The card must carry the duration.")
        self.assertIn("50", body, "The card must carry the real price.")
        self.assertIn(
            "More info", body,
            "The card's button is labelled 'More info'.",
        )

    def test_an_unpublished_tour_is_not_listed(self):
        self.tour.is_published = False

        self.assertNotIn("Blue Hole Dive", self.url_open("/tours").text)

    # --- One tour ----------------------------------------------------------

    def test_the_tour_page_renders_info_and_the_booking_widget(self):
        response = self.url_open(self.tour.website_url)

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn("Blue Hole Dive", body)
        self.assertIn("o_tour_widget", body, "The booking widget is missing.")
        self.assertIn("o_tour_calendar", body, "The calendar is missing.")
        self.assertIn("o_tour_pax", body, "The participant selector is missing.")

    def test_the_tour_page_shows_every_gallery_image(self):
        """Gallery images that are stored but never rendered are the easy thing
        to get wrong: nothing errors, the page just quietly lacks them."""
        for index in range(3):
            self.env["tour.tour.image"].create({
                "tour_id": self.tour.id,
                "name": "Gallery %s" % index,
                "sequence": index * 10,
                "image_1920": self.tour.image_1920 or IMAGE,
            })

        body = self.url_open(self.tour.website_url).text

        self.assertIn("o_tour_photos", body)
        # Asked for by id rather than counted. A tile carries two URLs for the
        # same photograph — the 512px one it draws and the full-size one the
        # lightbox opens — so a total of `/web/image/` occurrences stopped
        # being a count of photographs.
        for image in self.tour.image_ids:
            self.assertIn(
                "/web/image/tour.tour.image/%s/" % image.id, body,
                "%s is stored but never rendered." % image.name,
            )

    def test_an_unpublished_tour_page_is_not_found(self):
        self.tour.is_published = False

        response = self.url_open(self.tour.website_url)

        self.assertEqual(response.status_code, 404)

    def test_an_archived_tour_page_is_not_found(self):
        """Archiving is how an operator takes an experience off the books.

        It already removes the tour from the catalogue and from the website
        menu, so a page that keeps answering — with a calendar, and a button
        that still takes bookings — is the site disagreeing with itself about
        what is for sale.
        """
        url = self.tour.website_url
        self.tour.active = False

        response = self.url_open(url)

        self.assertEqual(response.status_code, 404)

    def test_an_archived_tour_offers_no_availability(self):
        month = self.departure.date.strftime("%Y-%m")
        self.tour.active = False

        self.assertEqual(self._availability(month)["days"], {})

    def test_an_archived_tour_cannot_be_booked(self):
        departure = self.departure
        # Read the token off the live page first: it belongs to the session
        # rather than to the page, and once the tour is archived there is no
        # page left to read it from. Without one the POST is refused as a
        # forgery and this would pass without ever reaching the controller.
        token = re.search(
            r'name="csrf_token"[^>]*value="([^"]+)"',
            self.url_open(self.tour.website_url).text,
        ).group(1)
        self.tour.active = False

        response = self.opener.post(
            self.base_url() + "/tour/book",
            data={"departure_id": departure.id, "pax": 1, "csrf_token": token},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            self.env["tour.booking"].search_count([("departure_id", "=", departure.id)]),
            0,
            "An archived experience sold a seat.",
        )

    # --- The availability feed --------------------------------------------

    def _availability(self, month=None):
        month = month or fields.Date.today().strftime("%Y-%m")
        return self.opener.post(
            self.base_url() + "/tour/%s/availability" % self.tour.id,
            json={"params": {"month": month}},
        ).json()["result"]

    def test_the_calendar_offers_a_day_with_an_open_departure(self):
        month = self.departure.date.strftime("%Y-%m")

        days = self._availability(month)["days"]

        self.assertIn(self.departure.date.isoformat(), days)

    def test_the_calendar_does_not_offer_a_sold_out_day(self):
        # Two bookings rather than one: the departure caps a single party at
        # six, and a sold-out boat is normally sold out by several parties.
        self._booking(departure=self.departure, pax=6)
        self._booking(departure=self.departure, pax=4, partner=self.other_partner)
        month = self.departure.date.strftime("%Y-%m")

        days = self._availability(month)["days"]

        self.assertNotIn(
            self.departure.date.isoformat(), days,
            "A departure with no seats left was still offered.",
        )

    def test_the_calendar_does_not_offer_a_day_past_the_cutoff(self):
        """The widget never decides what is bookable. It renders what the
        server hands it, so the cut-off is applied in exactly one place — the
        same one the booking itself is checked against."""
        soon = self.env["tour.departure"].create({
            "tour_id": self.tour.id,
            "date": fields.Date.today(),
            "start_datetime": fields.Datetime.now() + timedelta(hours=2),
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        })

        days = self._availability(soon.date.strftime("%Y-%m"))["days"]

        self.assertNotIn(soon.date.isoformat(), days)

    def test_the_calendar_does_not_offer_a_cancelled_departure(self):
        self.departure.action_cancel()
        month = self.departure.date.strftime("%Y-%m")

        days = self._availability(month)["days"]

        self.assertNotIn(self.departure.date.isoformat(), days)

    def test_the_calendar_reports_every_start_time_of_a_day(self):
        second = self.env["tour.departure"].create({
            "tour_id": self.tour.id,
            "date": self.departure.date,
            "start_datetime": self.departure.start_datetime + timedelta(hours=4),
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        })

        days = self._availability(self.departure.date.strftime("%Y-%m"))["days"]

        ids = {slot["id"] for slot in days[self.departure.date.isoformat()]}
        self.assertEqual(ids, {self.departure.id, second.id})

    def test_the_calendar_reports_times_in_the_tours_timezone(self):
        """The guest is told when the boat leaves, not what the server clock
        says.

        The tour runs on Curaçao, four hours behind UTC, so a 09:00 departure is
        stored as 13:00 UTC. Rendering that with the *viewer's* timezone — which
        for an anonymous visitor is the server's — advertises a 13:00 dive and
        sends people to the dock four hours late.
        """
        self.env.company.tour_tz = "America/Curacao"
        departure = self.env["tour.departure"].create({
            "tour_id": self.tour.id,
            "date": fields.Date.today() + timedelta(days=20),
            # 13:00 UTC == 09:00 in Curaçao, all year: no DST there.
            "start_datetime": fields.Datetime.to_datetime(
                "%s 13:00:00" % (fields.Date.today() + timedelta(days=20))
            ),
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        })

        days = self._availability(departure.date.strftime("%Y-%m"))["days"]

        slot = next(
            s for s in days[departure.date.isoformat()] if s["id"] == departure.id
        )
        self.assertEqual(
            slot["time"], "09:00",
            "The feed advertised the departure in the wrong timezone.",
        )

    def test_the_feed_says_nothing_about_an_unpublished_tour(self):
        self.tour.is_published = False

        self.assertEqual(self._availability()["days"], {})
