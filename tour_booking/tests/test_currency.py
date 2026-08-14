"""Pricing in one currency, charging in another.

The rule the whole file is about: everything is priced and taxed in the
company's own currency, and the *only* number that crosses into the settlement
currency is the one the payment provider is asked for — at a rate fixed once,
when the guest commits, and never recomputed afterwards.

We convert rather than letting the provider convert. A transaction raised in
euros for a figure we worked out comes back in euros for the same figure, so
the callback has nothing to reconcile and a refund has nothing to re-derive.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import HttpCase

from .common import TourCase

# Where `_record_charged_amount` reports a payment that does not match what was
# asked for. The two tests below provoke exactly that, so they capture the
# warning rather than letting a green run print one.
ANOMALY_LOGGER = "odoo.addons.tour_booking.models.tour_booking"


@tagged("post_install", "-at_install")
class TestSettlementCurrency(TourCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.euro = cls.env.ref("base.EUR")
        cls.euro.active = True
        # A rate that is nothing like 1, so a figure that skipped the
        # conversion is obvious rather than plausible.
        cls.env["res.currency.rate"].search([("currency_id", "=", cls.euro.id)]).unlink()
        cls.env["res.currency.rate"].create({
            "currency_id": cls.euro.id,
            "company_id": cls.env.company.id,
            "name": fields.Date.today() - timedelta(days=1),
            "rate": 0.90,
        })
        cls.departure = cls.env["tour.departure"].create({
            "tour_id": cls.tour.id,
            "date": fields.Date.today() + timedelta(days=10),
            "start_datetime": fields.Datetime.now() + timedelta(days=10),
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        })

    def _settle_in_euro(self, margin=0.0):
        self.env.company.write({
            "tour_settlement_currency_id": self.euro.id,
            "tour_fx_margin": margin,
        })

    def _booking(self, pax=2):
        return self.env["tour.booking"].create({
            "departure_id": self.departure.id,
            "partner_id": self.partner.id,
            "pax": pax,
        })

    # --- Configured off -----------------------------------------------------

    def test_without_a_settlement_currency_nothing_is_converted(self):
        """The case most operators are in, and the one every other test in the
        suite runs under: one currency, one number, no rate at all."""
        booking = self._booking(pax=2)

        amount, currency = booking.payment_amount()

        self.assertEqual(currency, booking.currency_id)
        self.assertEqual(amount, booking.amount_total)
        self.assertFalse(booking.fx_rate, "A rate was fixed with nothing to convert.")

    # --- Fixing the rate ----------------------------------------------------

    def test_creating_a_booking_fixes_the_rate_it_will_be_charged_at(self):
        self._settle_in_euro()

        booking = self._booking(pax=2)

        self.assertEqual(booking.settlement_currency_id, self.euro)
        self.assertAlmostEqual(booking.fx_rate, 0.90, places=6)
        self.assertEqual(booking.fx_rate_date, fields.Date.context_today(booking))
        # 2 x 50 USD at 0.90.
        self.assertEqual(booking.amount_settlement, 90.0)

    def test_the_margin_moves_the_rate_up(self):
        """It is the operator who is exposed between fixing a rate and the money
        landing, so the margin can only ever be in their favour."""
        self._settle_in_euro(margin=3.0)

        booking = self._booking(pax=2)

        self.assertAlmostEqual(booking.fx_rate, 0.90 * 1.03, places=6)
        self.assertEqual(booking.amount_settlement, 92.7)

    def test_the_stored_rate_is_the_effective_one(self):
        """Margin included, so nothing downstream can apply it a second time."""
        self._settle_in_euro(margin=10.0)

        booking = self._booking(pax=1)

        self.assertEqual(
            booking.amount_settlement,
            self.euro.round(booking.amount_total * booking.fx_rate),
            "The settlement total was not simply total x stored rate.",
        )

    def test_repricing_a_booking_does_not_move_its_rate(self):
        """Adding a wetsuit at checkout changes what is owed. It must not
        re-quote the rate the guest was already shown."""
        self._settle_in_euro()
        booking = self._booking(pax=2)
        original = booking.fx_rate

        wetsuit = self.env["tour.extra"].create({
            "name": "Wetsuit", "price": 10.0, "price_basis": "per_person",
        })
        self.env["tour.booking.extra"].create({
            "booking_id": booking.id, "extra_id": wetsuit.id, "quantity": 1,
        })

        self.assertEqual(booking.fx_rate, original)
        # 120 USD at the rate fixed when the booking was made.
        self.assertEqual(booking.amount_settlement, 108.0)

    def test_a_later_rate_change_leaves_existing_bookings_alone(self):
        self._settle_in_euro()
        booking = self._booking(pax=2)

        self.env["res.currency.rate"].create({
            "currency_id": self.euro.id,
            "company_id": self.env.company.id,
            "name": fields.Date.today() + timedelta(days=1),
            "rate": 0.50,
        })
        booking.invalidate_recordset()

        self.assertAlmostEqual(booking.fx_rate, 0.90, places=6)
        self.assertEqual(booking.amount_settlement, 90.0)

    # --- Paying -------------------------------------------------------------

    def test_the_payment_goes_out_in_the_settlement_currency(self):
        self._settle_in_euro()
        booking = self._booking(pax=2)

        amount, currency = booking.payment_amount()

        self.assertEqual(currency, self.euro)
        self.assertEqual(amount, 90.0)

    def test_what_was_charged_is_recorded_from_the_callback(self):
        self._settle_in_euro()
        booking = self._booking(pax=2)
        transaction = self._transaction(booking, "done")

        transaction._post_process()

        self.assertEqual(booking.state, "confirmed")
        self.assertEqual(booking.charged_amount, 90.0)
        self.assertAlmostEqual(booking.charged_fx_rate, 0.90, places=6)

    def test_a_payment_in_the_wrong_currency_records_nothing_and_says_so(self):
        """An anomaly, not a branch. The guest has paid, so the booking is
        confirmed either way — but nothing is written down as charged, because
        a refund would repay a figure nobody can vouch for."""
        self._settle_in_euro()
        booking = self._booking(pax=2)
        transaction = self._transaction(booking, "done")
        transaction.currency_id = booking.currency_id

        # The log line is half the point — an operator finds this months later
        # by grepping, not by opening a booking they have no reason to suspect.
        # Asserted rather than muted, so a passing run stays quiet either way.
        with self.assertLogs(ANOMALY_LOGGER, "WARNING") as logged:
            transaction._post_process()
        self.assertIn("was charged in", logged.output[0])

        self.assertEqual(booking.state, "confirmed")
        self.assertFalse(booking.charged_amount)
        self.assertTrue(
            any("came back in" in (m.body or "") for m in booking.message_ids),
            "Nothing on the booking says the currency was wrong.",
        )

    def test_a_payment_for_the_wrong_amount_is_recorded_and_flagged(self):
        """What was taken is what a refund repays, whatever we asked for."""
        self._settle_in_euro()
        booking = self._booking(pax=2)
        transaction = self._transaction(booking, "done")
        transaction.amount = 88.0

        with self.assertLogs(ANOMALY_LOGGER, "WARNING") as logged:
            transaction._post_process()
        self.assertIn("asked for", logged.output[0])

        self.assertEqual(booking.charged_amount, 88.0)
        self.assertTrue(
            any("asked for" in (m.body or "") for m in booking.message_ids),
            "A short payment went unremarked.",
        )

    # --- Refunding ----------------------------------------------------------

    def test_a_refund_repays_what_was_charged(self):
        self._settle_in_euro()
        policy = self.env["tour.cancellation.policy"].create({
            "name": "Full refund",
            "rule_ids": [(0, 0, {"hours_before": 24, "refund_percent": 100.0})],
        })
        booking = self._booking(pax=2)
        booking.cancellation_policy_id = policy
        self._transaction(booking, "done")._post_process()

        booking.action_cancel()

        self.assertEqual(booking.refund_amount, 90.0)
        self.assertEqual(booking.refund_amount, booking.charged_amount)

    def test_a_refund_is_never_a_fresh_conversion(self):
        """Today's rate is not the rate the guest paid at. Refunding at it hands
        the difference to whichever side the market happened to favour."""
        self._settle_in_euro()
        policy = self.env["tour.cancellation.policy"].create({
            "name": "Full refund",
            "rule_ids": [(0, 0, {"hours_before": 24, "refund_percent": 100.0})],
        })
        booking = self._booking(pax=2)
        booking.cancellation_policy_id = policy
        self._transaction(booking, "done")._post_process()

        self.env["res.currency.rate"].create({
            "currency_id": self.euro.id,
            "company_id": self.env.company.id,
            "name": fields.Date.today() + timedelta(days=1),
            "rate": 0.50,
        })
        booking.action_cancel()

        self.assertEqual(booking.refund_amount, 90.0, "It re-converted at today's rate.")

    def test_a_booking_that_was_never_paid_is_owed_nothing(self):
        self._settle_in_euro()
        policy = self.env["tour.cancellation.policy"].create({
            "name": "Full refund",
            "rule_ids": [(0, 0, {"hours_before": 24, "refund_percent": 100.0})],
        })
        booking = self._booking(pax=2)
        booking.cancellation_policy_id = policy

        booking.action_cancel()

        self.assertEqual(booking.refund_amount, 0.0)


@tagged("post_install", "-at_install")
class TestSettlementOnThePage(HttpCase, TourCase):
    """What a guest is told, and how firmly."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tour.is_published = True
        cls.euro = cls.env.ref("base.EUR")
        cls.euro.active = True
        cls.env["res.currency.rate"].search([("currency_id", "=", cls.euro.id)]).unlink()
        cls.env["res.currency.rate"].create({
            "currency_id": cls.euro.id,
            "company_id": cls.env.company.id,
            "name": fields.Date.today() - timedelta(days=1),
            "rate": 0.90,
        })
        cls.env.company.tour_settlement_currency_id = cls.euro.id
        cls.departure = cls.env["tour.departure"].create({
            "tour_id": cls.tour.id,
            "date": fields.Date.today() + timedelta(days=10),
            "start_datetime": fields.Datetime.now() + timedelta(days=10),
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        })

    def test_the_tour_page_hands_the_widget_todays_rate(self):
        """The browsing figure is an approximation and is drawn from a rate the
        page carries, not from one the browser invents."""
        body = self.url_open(self.tour.website_url).text

        self.assertIn("data-settlement-rate=", body)
        self.assertIn("o_tour_total_settlement", body)

    def test_the_checkout_states_the_charge_rather_than_estimating_it(self):
        booking = self.env["tour.booking"].create({
            "departure_id": self.departure.id,
            "partner_id": self.partner.id,
            "pax": 2,
        })

        body = self.url_open(booking._checkout_url()).text

        self.assertIn("Charged as", body)
        self.assertIn("90.00", body)
