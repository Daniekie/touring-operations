from datetime import date, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TourCase(TransactionCase):
    """Fixtures shared by the suite.

    Dates are anchored well into the future rather than relative to today where
    a test cares about a cut-off, so that a suite run at 23:55 does not fail for
    reasons that have nothing to do with the code.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # The timezone lives on the company, not the tour. Amsterdam because
        # the generation tests need somewhere that actually observes DST.
        cls.env.company.tour_tz = "Europe/Amsterdam"

        cls.partner = cls.env["res.partner"].create({"name": "Test Guest"})
        cls.other_partner = cls.env["res.partner"].create({"name": "Second Guest"})

        cls.tour = cls.env["tour.tour"].create({
            "name": "Blue Hole Dive",
            "duration_hours": 3.0,
            "default_capacity": 10,
            "booking_cutoff_hours": 24,
            "has_specific_time": True,
            "price_per_person": 50.0,
            "start_time_ids": [
                (0, 0, {"time_of_day": 9.0}),
                (0, 0, {"time_of_day": 14.5}),
            ],
        })

        # A Monday, so weekday arithmetic in the tests is easy to read.
        cls.monday = date(2027, 3, 1)

        cls._setup_payment()

    # --- Payment ------------------------------------------------------------

    @classmethod
    def _setup_payment(cls):
        """A dummy payment provider for the whole class.

        Built in `setUpClass` rather than lazily on first use. A provider
        created inside a test lives in that test's savepoint, which is rolled
        back afterwards — while a cached reference to it would survive on the
        class and hand the next test a `MissingError` on a record that no longer
        exists.

        A test database has no provider configured at all, so without this every
        transaction fails its not-null constraint on `provider_id`. Code `none`
        is Odoo's own stand-in for "no real provider implementation", which is
        what these tests want: they care about the state of a transaction, not
        about talking to a bank.
        """
        method = cls.env.ref("payment.payment_method_unknown")
        # Order matters: a payment method refuses to be activated until an
        # enabled provider supports it, so the provider has to exist first.
        # The journal is not optional. `account_payment` is auto-installed
        # alongside `account` and `payment`, and its `_post_process` creates an
        # `account.payment`. Without a journal on the provider,
        # `_ensure_payment_method_line` never creates the
        # `account.payment.method.line`, and every `_post_process` test dies on
        # "Please define a payment method line on your payment."
        journal = cls.env["account.journal"].create({
            "name": "Test Bank",
            "code": "TBNK",
            "type": "bank",
        })
        # `_setup_payment_method` explicitly skips the codes `none` and
        # `custom`, so the dummy provider below can never grow an
        # `account.payment.method` of its own — and without one,
        # `_ensure_payment_method_line` returns early however good the journal
        # is. Creating it here is what makes the journal count.
        cls.env["account.payment.method"].sudo().create({
            "name": "Test Provider",
            "code": "none",
            "payment_type": "inbound",
        })
        cls.provider = cls.env["payment.provider"].create({
            "name": "Test Provider",
            "code": "none",
            "state": "test",
            "payment_method_ids": [(6, 0, method.ids)],
            "journal_id": journal.id,
        })
        method.active = True

    def _transaction(self, booking, state="done", reference=None):
        """A payment transaction attached to `booking`, in the given state.

        Created as a draft and then moved with SQL rather than through the ORM.
        `payment` guards some states with constraints about what a provider
        supports — `authorized` needs manual capture, which is a non-stored
        compute a dummy provider cannot claim — and these tests are about which
        transaction states the reaper respects, not about re-litigating
        `payment`'s own invariants.
        """
        provider = self.provider
        transaction = self.env["payment.transaction"].create({
            "provider_id": provider.id,
            "payment_method_id": provider.payment_method_ids[:1].id,
            "amount": booking.amount_total,
            "currency_id": booking.currency_id.id,
            "partner_id": booking.partner_id.id,
            "reference": reference or "test-%s-%s" % (booking.id, state),
        })
        if state != "draft":
            self.env.flush_all()
            self.env.cr.execute(
                "UPDATE payment_transaction SET state = %s WHERE id = %s",
                [state, transaction.id],
            )
            transaction.invalidate_recordset(["state"])
        booking.transaction_ids = [(4, transaction.id)]
        return transaction

    # --- Tax ----------------------------------------------------------------

    @classmethod
    def _tax(cls, percent):
        """A sale tax.

        The group and the country are both spelled out because a test database
        has no chart of accounts installed, so the defaults that would normally
        precompute them have nothing to find.
        """
        country = cls.env.company.account_fiscal_country_id or cls.env.ref("base.nl")
        group = cls.env["account.tax.group"].create({
            "name": "Test Tax Group",
            "country_id": country.id,
        })
        return cls.env["account.tax"].create({
            "name": "Test %s%%" % percent,
            "amount": percent,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "tax_group_id": group.id,
            "country_id": country.id,
        })

    @classmethod
    def _rule(cls, tour=None, **overrides):
        values = {
            "tour_id": (tour or cls.tour).id,
            "date_from": cls.monday,
            "date_to": cls.monday + timedelta(days=27),
            "recurrence": "weekly",
            "mon": True,
            "min_pax": 1,
            "max_pax": 6,
        }
        values.update(overrides)
        return cls.env["tour.availability.rule"].create(values)

    @classmethod
    def _generate(cls, rules, horizon_end=None):
        return cls.env["tour.departure"]._generate(
            rules, horizon_end or (cls.monday + timedelta(days=27))
        )

    def _departure(self, **overrides):
        """One departure, made directly rather than through a rule.

        Most tests are about what happens to seats, not about how the departure
        came to exist, and going through the generator would make them depend on
        the recurrence logic as well.
        """
        values = {
            "tour_id": self.tour.id,
            "date": self.monday,
            "start_datetime": fields.Datetime.now() + timedelta(days=30),
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        }
        values.update(overrides)
        return self.env["tour.departure"].create(values)

    def _booking(self, departure=None, pax=2, partner=None, **overrides):
        values = {
            "departure_id": (departure or self._departure()).id,
            "partner_id": (partner or self.partner).id,
            "pax": pax,
        }
        values.update(overrides)
        return self.env["tour.booking"].create(values)
