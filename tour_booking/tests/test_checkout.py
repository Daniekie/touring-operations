import re

from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import HttpCase

from .common import TourCase


@tagged("post_install", "-at_install")
class TestCheckout(HttpCase, TourCase):
    """Draft before the redirect, confirmed after the callback — and confirmed
    exactly once however many times the callback arrives."""

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
        cls.wetsuit = cls.env["tour.extra"].create({
            "name": "Wetsuit",
            "price": 10.0,
            "price_basis": "per_person",
        })
        cls.hotel = cls.env["tour.question"].create({
            "name": "Which hotel?",
            "field_type": "text",
            "scope": "per_booking",
            "required": True,
        })
        cls.tour.extra_ids = [(6, 0, cls.wetsuit.ids)]
        cls.tour.question_ids = [(6, 0, cls.hotel.ids)]

    def _csrf_token(self, url):
        """Pull a live CSRF token out of a rendered page.

        Odoo rejects an unauthenticated POST without one, and the token is tied
        to the session cookie `self.opener` is already carrying — so it has to
        be read from a page fetched in this same session rather than minted.
        """
        body = self.url_open(url).text
        match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body)
        self.assertTrue(match, "No CSRF token on %s" % url)
        return match.group(1)

    def _draft(self, pax=2):
        return self.env["tour.booking"].create({
            "departure_id": self.departure.id,
            "partner_id": self.partner.id,
            "pax": pax,
        })

    def _post(self, url, page, **data):
        """POST a form the way a browser would, token and all."""
        return self.url_open(url, data=dict(data, csrf_token=self._csrf_token(page)))

    # --- Creating the draft -------------------------------------------------

    def test_booking_from_the_widget_creates_a_draft_holding_its_seats(self):
        booking = self._draft(pax=3)

        self.assertEqual(booking.state, "draft")
        self.assertEqual(
            self.departure.seats_sold, 3,
            "A draft must hold its seats for the duration of the redirect, or "
            "two guests can pay for the same last place.",
        )

    def test_the_checkout_page_opens_with_a_valid_token(self):
        booking = self._draft(pax=2)

        response = self.url_open(booking._checkout_url())

        self.assertEqual(response.status_code, 200)
        self.assertIn("Complete your booking", response.text)

    def test_the_checkout_page_refuses_a_wrong_token(self):
        booking = self._draft(pax=2)

        response = self.url_open(
            "/tour/booking/%s?access_token=nonsense" % booking.id,
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303, "It should redirect away.")

    # --- Confirmation on the callback --------------------------------------

    def _paid(self, booking):
        transaction = self._transaction(booking, "done")
        return transaction

    def test_a_successful_payment_confirms_the_booking(self):
        booking = self._draft(pax=2)
        self.env["tour.booking.answer"].create({
            "booking_id": booking.id,
            "question_id": self.hotel.id,
            "value_char": "Hotel Bonaire",
        })
        transaction = self._paid(booking)

        transaction._post_process()

        self.assertEqual(booking.state, "confirmed")

    def test_a_repeated_callback_does_not_confirm_twice(self):
        """Providers retry webhooks and guests refresh return pages. A second
        callback must be a no-op, not a second seat taken."""
        booking = self._draft(pax=2)
        self.env["tour.booking.answer"].create({
            "booking_id": booking.id,
            "question_id": self.hotel.id,
            "value_char": "Hotel Bonaire",
        })
        transaction = self._paid(booking)

        transaction._post_process()
        transaction._post_process()

        self.assertEqual(booking.state, "confirmed")
        self.assertEqual(
            self.departure.seats_sold, 2,
            "The second callback took the seats a second time.",
        )

    def test_a_callback_never_revives_a_cancelled_booking(self):
        booking = self._draft(pax=2)
        transaction = self._paid(booking)
        booking.action_cancel()

        transaction._post_process()

        self.assertEqual(
            booking.state, "cancelled",
            "A late callback confirmed a booking the guest had cancelled.",
        )

    def test_a_failed_payment_leaves_the_booking_in_draft(self):
        booking = self._draft(pax=2)
        transaction = self._transaction(booking, "error")

        transaction._post_process()

        self.assertEqual(booking.state, "draft")

    # --- Details ------------------------------------------------------------

    def test_saving_details_prices_extras_into_the_total(self):
        booking = self._draft(pax=2)

        self._post(
            "/tour/booking/%s/details" % booking.id,
            booking._checkout_url(),
            access_token=booking._portal_ensure_token(),
            name="Danique",
            email="guest@example.com",
            **{
                "extra_%s" % self.wetsuit.id: 1,
                "question_%s_0" % self.hotel.id: "Hotel Bonaire",
            },
        )
        booking.invalidate_recordset()

        self.assertEqual(len(booking.extra_line_ids), 1)
        # 2 x 50 for the dive, plus 2 x 10 of wetsuit.
        self.assertEqual(booking.amount_total, 120.0)
        self.assertEqual(booking.answer_ids.value_char, "Hotel Bonaire")

    def test_a_price_sent_by_the_browser_is_ignored(self):
        """The only number that counts is the one computed on the server."""
        booking = self._draft(pax=2)

        self._post(
            "/tour/booking/%s/details" % booking.id,
            booking._checkout_url(),
            access_token=booking._portal_ensure_token(),
            name="Danique",
            email="guest@example.com",
            amount_total=1.0,
            price_per_person=0.01,
        )
        booking.invalidate_recordset()

        self.assertEqual(booking.amount_total, 100.0)
