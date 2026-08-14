import re

from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import HttpCase
from odoo.tools import mute_logger

from odoo.addons.tour_booking.controllers.checkout import MAX_OPEN_DRAFTS

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

    def _book_now(self, pax=1):
        """Press Book now the way the widget does."""
        return self._post(
            "/tour/book",
            self.tour.website_url,
            departure_id=self.departure.id,
            pax=pax,
        )

    def test_a_visitor_cannot_hold_a_boat_by_pressing_book_now_over_and_over(self):
        """Every press takes seats and holds them for half an hour.

        Nothing about a draft requires the guest to come back, so without a
        limit one visitor — or one crawler with a token — can empty a departure
        and keep it empty, at no cost and with nothing to undo it but the
        reaper.
        """
        for _ in range(MAX_OPEN_DRAFTS):
            self.assertEqual(self._book_now().status_code, 200)
        opened = self.env["tour.booking"].search_count([
            ("departure_id", "=", self.departure.id), ("state", "=", "draft"),
        ])

        response = self._book_now()

        self.assertIn("could not be booked", response.text)
        self.assertEqual(
            self.env["tour.booking"].search_count([
                ("departure_id", "=", self.departure.id), ("state", "=", "draft"),
            ]),
            opened,
            "A visitor already sitting on the limit opened another draft.",
        )

    def test_finishing_a_booking_frees_the_visitor_to_make_another(self):
        """The limit is on drafts left hanging, not on how much a guest may
        buy."""
        for _ in range(MAX_OPEN_DRAFTS):
            self._book_now()
        held = self.env["tour.booking"].search([
            ("departure_id", "=", self.departure.id), ("state", "=", "draft"),
        ])
        held[0].action_cancel()

        response = self._book_now()

        self.assertNotIn("could not be booked", response.text)

    def test_the_checkout_page_opens_with_a_valid_token(self):
        booking = self._draft(pax=2)

        response = self.url_open(booking._checkout_url())

        self.assertEqual(response.status_code, 200)
        self.assertIn("Complete your booking", response.text)

    def test_the_checkout_page_opens_for_a_provider_that_can_save_a_card(self):
        """`payment.form` indexes `show_tokenize_input_mapping` by provider id
        rather than looking the id up with a default, so a mapping that is
        missing an entry is a 500 on the payment step — and only for operators
        whose provider happens to support tokenization, which is most of the
        real ones.
        """
        # Published, because a provider a public visitor cannot see is a
        # provider `_get_compatible_providers` filters out — and a checkout with
        # no providers at all renders the buttons that were missing here.
        self.provider.is_published = True
        self.provider.allow_tokenization = True
        self.provider.payment_method_ids.support_tokenization = True
        booking = self._draft(pax=2)

        response = self.url_open(booking._checkout_url())

        self.assertEqual(response.status_code, 200)
        self.assertIn("Complete your booking", response.text)

    # The refusal is an `AccessError`, which Odoo logs as a warning on its way
    # out of the controller. That is right on a live instance and noise here:
    # this test exists to make it happen.
    @mute_logger("odoo.http")
    def test_the_checkout_page_refuses_a_wrong_token(self):
        booking = self._draft(pax=2)

        response = self.url_open(
            "/tour/booking/%s?access_token=nonsense" % booking.id,
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 303, "It should redirect away.")

    # --- Whose contact the details step may rewrite -------------------------

    def _save_details(self, booking, **fields_):
        return self._post(
            "/tour/booking/%s/details" % booking.id,
            booking._checkout_url(),
            access_token=booking.access_token,
            **fields_,
        )

    def test_the_details_step_does_not_rewrite_a_contact_it_did_not_make(self):
        """The access token is a key to one booking, not to a contact record.

        A desk user books a seat for a regular customer; the token goes out by
        email, or into a browser history, or to whoever the guest forwards it
        to. Whoever holds it could overwrite that customer's name, phone and —
        the one that matters — email address.
        """
        customer = self.env["res.partner"].create({
            "name": "Regular Customer", "email": "regular@example.com",
        })
        booking = self.env["tour.booking"].create({
            "departure_id": self.departure.id,
            "partner_id": customer.id,
            "pax": 1,
        })

        self._save_details(booking, name="Someone Else", email="attacker@example.com")

        self.assertEqual(customer.name, "Regular Customer")
        self.assertEqual(
            customer.email, "regular@example.com",
            "A booking token rewrote a customer's email address.",
        )
        self.assertNotEqual(
            booking.partner_id, customer,
            "The booking should have been moved onto a contact of its own.",
        )
        self.assertEqual(booking.partner_id.email, "attacker@example.com")

    def test_a_guest_can_still_correct_their_own_details(self):
        """The contact the checkout made for them is theirs to edit, and
        editing it must not spawn a new one on every save.

        Booked through the site rather than by hand, because the thing under
        test is precisely how the contact came to exist: an anonymous visitor
        starts on the shared public partner and is given one of their own at
        this step.
        """
        booking = self.env["tour.booking"].browse(int(
            self._book_now().url.split("/tour/booking/")[1].split("?")[0]
        ))
        self.assertTrue(booking.partner_id)

        self._save_details(booking, name="Guest", email="guest@example.com")
        theirs = booking.partner_id
        self._save_details(booking, name="Guest Corrected", email="guest@example.com")

        self.assertEqual(booking.partner_id, theirs, "A second contact was created.")
        self.assertEqual(theirs.name, "Guest Corrected")

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

    def test_a_payment_against_a_cancelled_departure_does_not_break_the_callback(self):
        """The money is already taken by the time this runs.

        Raising out of `_post_process` leaves the guest paid and unconfirmed,
        rolls back everything the callback did, and hands the provider an error
        it will retry forever. The booking cannot be confirmed — there is no
        seat to confirm it onto — but that has to be recorded, not thrown.
        """
        booking = self._draft(pax=2)
        self.env["tour.booking.answer"].create({
            "booking_id": booking.id,
            "question_id": self.hotel.id,
            "value_char": "Hotel Bonaire",
        })
        transaction = self._paid(booking)
        self.departure.action_cancel()

        with mute_logger("odoo.addons.tour_booking.models.payment_transaction"):
            transaction._post_process()

        self.assertEqual(booking.state, "draft")
        self.assertTrue(
            booking.message_ids.filtered(lambda m: "could not be confirmed" in (m.body or "")),
            "Nothing on the booking says a paid guest has no seat.",
        )

    def test_one_booking_that_cannot_confirm_does_not_hold_up_the_others(self):
        """One transaction, several bookings: the failure has to be contained."""
        first = self._draft(pax=1)
        second = self._draft(pax=1)
        for booking in (first, second):
            self.env["tour.booking.answer"].create({
                "booking_id": booking.id,
                "question_id": self.hotel.id,
                "value_char": "Hotel Bonaire",
            })
        transaction = self._paid(first)
        transaction.tour_booking_ids = [(4, second.id)]
        # Only the first one's departure is pulled out from under it.
        doomed = self.env["tour.departure"].create({
            "tour_id": self.tour.id,
            "date": fields.Date.today() + timedelta(days=11),
            "start_datetime": fields.Datetime.now() + timedelta(days=11),
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        })
        first.departure_id = doomed
        doomed.action_cancel()

        with mute_logger("odoo.addons.tour_booking.models.payment_transaction"):
            transaction._post_process()

        self.assertEqual(first.state, "draft")
        self.assertEqual(
            second.state, "confirmed",
            "A guest with a perfectly good seat was left unconfirmed by "
            "somebody else's cancelled departure.",
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

    # --- The live total -----------------------------------------------------

    def _reprice(self, booking, **quantities):
        response = self.url_open(
            "/tour/booking/%s/extras" % booking.id,
            json={"params": dict(
                quantities, access_token=booking._portal_ensure_token()
            )},
        )
        return response.json()["result"]

    def test_choosing_an_extra_reprices_the_summary_there_and_then(self):
        """The total used to move only when Save details was pressed, so adding
        a wetsuit changed nothing on the page."""
        booking = self._draft(pax=2)

        result = self._reprice(booking, **{"extra_%s" % self.wetsuit.id: 1})
        booking.invalidate_recordset()

        # 2 x 50 for the dive, plus 2 x 10 of wetsuit.
        self.assertEqual(booking.amount_total, 120.0)
        self.assertIn("120", result["html"])

    def test_the_extras_are_saved_not_merely_quoted(self):
        """A guest who picks an extra and goes straight to the payment buttons
        must be charged what the summary told them."""
        booking = self._draft(pax=2)

        self._reprice(booking, **{"extra_%s" % self.wetsuit.id: 2})
        booking.invalidate_recordset()

        self.assertEqual(booking.extra_line_ids.quantity, 2)

    def test_removing_an_extra_takes_it_back_out_of_the_total(self):
        booking = self._draft(pax=2)
        self._reprice(booking, **{"extra_%s" % self.wetsuit.id: 1})

        self._reprice(booking, **{"extra_%s" % self.wetsuit.id: 0})
        booking.invalidate_recordset()

        self.assertFalse(booking.extra_line_ids)
        self.assertEqual(booking.amount_total, 100.0)

    @mute_logger("odoo.http")
    def test_repricing_refuses_a_wrong_token(self):
        booking = self._draft(pax=2)

        response = self.url_open(
            "/tour/booking/%s/extras" % booking.id,
            json={"params": {"access_token": "nonsense",
                             "extra_%s" % self.wetsuit.id: 5}},
        )
        booking.invalidate_recordset()

        self.assertIn("error", response.json())
        self.assertFalse(booking.extra_line_ids, "It priced somebody else's booking.")

    def test_the_boxes_remember_what_is_already_on_the_booking(self):
        """The page is re-rendered after Save details and after a failed
        payment. A box that reset to zero would disagree with the total next to
        it."""
        booking = self._draft(pax=2)
        self._reprice(booking, **{"extra_%s" % self.wetsuit.id: 3})

        body = self.url_open(booking._checkout_url()).text

        box = re.search(
            r'<input[^>]*name="extra_%s"[^>]*>' % self.wetsuit.id, body
        )
        self.assertIsNotNone(box, "The extras box is not on the page at all.")
        self.assertIn('value="3"', box.group(0))

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
