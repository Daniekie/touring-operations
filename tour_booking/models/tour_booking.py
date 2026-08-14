import logging

from collections import defaultdict

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..const import DEAD_TRANSACTION_STATES, SEAT_HOLDING_STATES

_logger = logging.getLogger(__name__)

# How long a checkout may sit unfinished before its seats go back on sale.
DRAFT_LIFETIME_MINUTES = 30


class TourBooking(models.Model):
    """Seats on one departure, sold to one guest.

    A booking holds its seats from the moment it is created, draft or not. That
    is deliberate: the guest is redirected to a payment provider straight after,
    and if the draft did not hold the seats, two people could pay for the same
    last place. The reaper below puts abandoned drafts back on sale.
    """

    _name = "tour.booking"
    _description = "Tour Booking"
    _inherit = ["portal.mixin", "mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, copy=False, readonly=True, default="/")
    departure_id = fields.Many2one(
        "tour.departure", string="Trip", required=True, ondelete="restrict",
        index=True,
    )
    tour_id = fields.Many2one(related="departure_id.tour_id", store=True, index=True)
    start_datetime = fields.Datetime(related="departure_id.start_datetime", store=True)
    partner_id = fields.Many2one("res.partner", string="Guest", required=True, index=True)
    partner_email = fields.Char(related="partner_id.email", string="Email", readonly=True)
    partner_phone = fields.Char(related="partner_id.phone", string="Phone", readonly=True)
    company_id = fields.Many2one(related="departure_id.company_id", store=True)
    currency_id = fields.Many2one(related="departure_id.currency_id")

    pax = fields.Integer(string="Participants", required=True, default=1)

    # --- What this booking was sold at -------------------------------------
    #
    # Copied from the tour when the booking is made, not read through it. A
    # price is what the guest agreed to pay on the day, and a tour's price is
    # the price of the *next* seat sold: reading it live meant that raising it
    # for next season rewrote the total of every booking ever taken, paid ones
    # included, which then read as underpaid by the difference. The extras
    # already freeze their unit price for exactly this reason; see
    # `tour.booking.extra.unit_price`.
    #
    # `copy=False` on both, so duplicating a booking is a new sale quoted at
    # today's price rather than one that inherits a frozen one.
    price_per_person = fields.Monetary(
        string="Price per Person",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        help="The per-person price this booking was sold at. Fixed when the "
             "booking was created; changing the tour's price does not move it.",
    )
    tax_ids = fields.Many2many(
        "account.tax",
        string="Taxes",
        copy=False,
        help="The taxes in force when this booking was sold.",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled")],
        required=True,
        default="draft",
        index=True,
        tracking=True,
    )

    extra_line_ids = fields.One2many("tour.booking.extra", "booking_id")
    answer_ids = fields.One2many("tour.booking.answer", "booking_id")

    amount_untaxed = fields.Monetary(compute="_compute_amounts", store=True)
    amount_tax = fields.Monetary(compute="_compute_amounts", store=True)
    amount_total = fields.Monetary(compute="_compute_amounts", store=True)

    # --- Settlement --------------------------------------------------------
    #
    # The three amounts above are the booking, in the company's own currency:
    # that is what the price list says, what tax was computed on, and what the
    # books are kept in. Nothing below ever feeds back into them.
    #
    # Below is what the payment provider is asked for. We convert rather than
    # letting the provider convert, so the transaction goes out in the currency
    # it settles in and comes back in the same one — there is nothing left for
    # the two sides to disagree about in the callback.
    settlement_currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_settlement_currency",
        store=True,
        string="Settlement Currency",
    )
    fx_rate = fields.Float(
        string="Exchange Rate",
        digits=(16, 6),
        readonly=True,
        copy=False,
        help="Settlement currency per unit of the accounting currency, margin "
             "included. Fixed when the booking is created and never recomputed.",
    )
    fx_rate_date = fields.Date(readonly=True, copy=False)
    amount_settlement = fields.Monetary(
        compute="_compute_amount_settlement",
        store=True,
        currency_field="settlement_currency_id",
        string="Total to Pay",
        help="The total at the rate fixed when this booking was created. This "
             "is the figure the guest is charged, not an approximation of it.",
    )
    charged_amount = fields.Monetary(
        currency_field="settlement_currency_id",
        readonly=True,
        copy=False,
        string="Amount Charged",
        help="What the provider reported taking. Normally identical to the "
             "total above, since that is the amount it was asked for. A refund "
             "repays this figure, never a fresh conversion.",
    )
    charged_fx_rate = fields.Float(
        digits=(16, 6), readonly=True, copy=False, string="Rate Charged At"
    )
    amount_paid = fields.Monetary(
        compute="_compute_amount_paid", store=True,
        currency_field="settlement_currency_id",
    )

    transaction_ids = fields.Many2many(
        "payment.transaction",
        "tour_booking_transaction_rel",
        "booking_id",
        "transaction_id",
        string="Payment Transactions",
        copy=False,
    )

    # The policy is snapshotted, not read through the tour. Editing a policy
    # must never silently rewrite the terms of a booking already sold.
    cancellation_policy_id = fields.Many2one(
        "tour.cancellation.policy", string="Cancellation Policy", readonly=True
    )
    cancelled_on = fields.Datetime(readonly=True, copy=False)
    refund_percent = fields.Float(compute="_compute_refund", store=True)
    refund_amount = fields.Monetary(
        compute="_compute_refund", store=True,
        currency_field="settlement_currency_id",
    )

    # --- Computes ----------------------------------------------------------

    @api.depends(
        "pax",
        "price_per_person",
        "tax_ids",
        "extra_line_ids.price_subtotal",
        "extra_line_ids.is_taxable",
    )
    def _compute_amounts(self):
        """Price the booking server-side.

        Never read a total from the browser, not even as a cross-check: the only
        number that matters is the one computed here.

        Everything this reads belongs to the booking. Depending on the tour's
        own price and taxes would put every sold booking back in reach of a
        price change made months later.
        """
        for booking in self:
            taxes = booking.tax_ids
            taxable = booking.pax * booking.price_per_person
            untaxed_only = 0.0
            for line in booking.extra_line_ids:
                if line.is_taxable:
                    taxable += line.price_subtotal
                else:
                    untaxed_only += line.price_subtotal

            if taxes:
                # `compute_all` rather than a percentage of our own: it is what
                # handles price-included taxes, and getting that wrong shows up
                # as money.
                result = taxes.compute_all(
                    taxable, currency=booking.currency_id, quantity=1.0
                )
                booking.amount_untaxed = result["total_excluded"] + untaxed_only
                booking.amount_tax = result["total_included"] - result["total_excluded"]
            else:
                booking.amount_untaxed = taxable + untaxed_only
                booking.amount_tax = 0.0
            booking.amount_total = booking.amount_untaxed + booking.amount_tax

    @api.depends("company_id.tour_settlement_currency_id", "currency_id")
    def _compute_settlement_currency(self):
        """What the provider will be asked to charge in.

        Falls back to the accounting currency rather than to nothing, so that an
        operator whose provider charges in their own currency has no second
        currency anywhere: the rate is 1, `amount_settlement` is `amount_total`,
        and every branch below collapses to the case that existed before any of
        this was here.

        A booking that has already fixed a rate keeps the currency that rate is
        in. Otherwise an operator switching providers next season would move
        every historical booking's settlement currency and leave its rate
        behind, and each of them would read as a euro figure at a pound rate.
        """
        for booking in self:
            if booking.fx_rate and booking.settlement_currency_id:
                continue
            booking.settlement_currency_id = (
                booking.company_id.tour_settlement_currency_id
                or booking.currency_id
            )

    @api.depends("amount_total", "fx_rate", "settlement_currency_id")
    def _compute_amount_settlement(self):
        """The total, in the currency the guest is charged in.

        Always computed from the *stored* rate. A version of this that fetched
        today's rate would quietly re-quote every booking on every recompute,
        which is the one thing fixing a rate is meant to prevent.
        """
        for booking in self:
            if booking.settlement_currency_id == booking.currency_id:
                booking.amount_settlement = booking.amount_total
            elif not booking.fx_rate:
                booking.amount_settlement = 0.0
            else:
                booking.amount_settlement = booking.settlement_currency_id.round(
                    booking.amount_total * booking.fx_rate
                )

    @api.depends("transaction_ids.state", "transaction_ids.amount")
    def _compute_amount_paid(self):
        """What the guest actually handed over, not what was invoiced.

        In the settlement currency, because that is what the transaction was
        raised in and what came back.
        """
        for booking in self:
            booking.amount_paid = sum(
                tx.amount for tx in booking.transaction_ids if tx.state == "done"
            )

    @api.depends(
        "cancelled_on",
        "amount_paid",
        "charged_amount",
        "amount_settlement",
        "cancellation_policy_id",
        "cancellation_policy_id.rule_ids.hours_before",
        "cancellation_policy_id.rule_ids.refund_percent",
        "departure_id.start_datetime",
    )
    def _compute_refund(self):
        """What was actually refundable, for a booking that was cancelled.

        Every input is stored, which is the only reason storing the result is
        sound. A version of this that read `fields.Datetime.now()` would freeze
        at whatever it happened to be when the row was last written and then
        misreport for the rest of the booking's life. The "if you cancel now you
        would get X" figure a guest sees *before* deciding is a different thing
        entirely, and is not a field: see `_refund_preview`.

        The percentage applies to what was actually paid, not to what was
        invoiced. A guest who cancels a booking they never paid for is owed
        nothing, whatever the policy says.
        """
        for booking in self:
            if not booking.cancelled_on or not booking.cancellation_policy_id:
                booking.refund_percent = 0.0
                booking.refund_amount = 0.0
                continue
            percent = booking.cancellation_policy_id._refund_percent_at(
                booking.departure_id.start_datetime, booking.cancelled_on
            )
            booking.refund_percent = percent
            booking.refund_amount = booking._refundable_base() * percent / 100.0

    def _refundable_base(self):
        """The figure a refund is a percentage of. -> float, settlement currency.

        What was charged, or failing that what this booking asked to be charged
        — never a fresh conversion. Today's rate is not the rate the guest paid
        at, and refunding at it hands the difference to whichever side the
        market happened to favour.

        Nothing paid means nothing to give back, whatever the policy says.
        """
        self.ensure_one()
        if self.charged_amount:
            return self.charged_amount
        return self.amount_settlement if self.amount_paid else 0.0

    def _refund_preview(self, when=None):
        """What the guest would get back if they cancelled at `when`. -> float.

        In the settlement currency, like the refund it previews: a guest who
        paid €135 is asking what of that €135 comes back.

        A method and not a field, on purpose: the answer depends on the current
        time, so it has to be recomputed on every page load rather than stored.
        """
        self.ensure_one()
        if not self.cancellation_policy_id or not self._can_cancel():
            return 0.0
        percent = self.cancellation_policy_id._refund_percent_at(
            self.departure_id.start_datetime, when or fields.Datetime.now()
        )
        return self._refundable_base() * percent / 100.0

    def _extra_quantity(self, extra):
        """How many of `extra` this booking has taken. -> int.

        For the checkout boxes, which are drawn once per `tour.extra` on the
        tour rather than once per line on the booking — so the line, if there
        is one, has to be looked up the other way round.
        """
        self.ensure_one()
        line = self.extra_line_ids.filtered(lambda l: l.extra_id == extra)[:1]
        return line.quantity if line else 0

    def _compute_access_url(self):
        super()._compute_access_url()
        for booking in self:
            booking.access_url = "/tour/booking/%s" % booking.id

    def _checkout_url(self):
        """The guest's own URL for this booking, token and all.

        The whole flow starts before anybody logs in, so the token is the only
        credential there is; building the URL in one place keeps it from being
        assembled by hand — and forgotten — at each redirect.
        """
        self.ensure_one()
        return "/tour/booking/%s?access_token=%s" % (
            self.id, self._portal_ensure_token()
        )

    @api.model
    def get_empty_list_help(self, help_message):
        """The first screen of a fresh database, which is otherwise a dead end.

        Bookings is the landing screen, and on day one it is empty for a reason
        nobody can act on from here: there is nothing on sale yet. "No bookings
        yet" is true and useless. When the catalogue is empty, say where to go
        instead — and only then, because once an experience exists the ordinary
        message is the right one again.
        """
        if self.env["tour.tour"].search_count([], limit=1):
            return super().get_empty_list_help(help_message)
        return Markup(
            '<p class="o_view_nocontent_smiling_face">%s</p><p>%s</p>'
        ) % (
            _("Nothing is on sale yet"),
            Markup(_(
                "In the top menu go to "
                "<b>Experiences → Create new Experience</b> to get started. "
                "Once an experience has availability, its trips appear in the "
                "Calendar and guests can book a seat on one."
            )),
        )

    # --- Constraints -------------------------------------------------------

    @api.constrains("pax", "departure_id")
    def _check_party_size(self):
        """Party size limits, which are limits on *one* booking.

        Not a viability threshold: `min_pax` does not mean the departure only
        runs once that many people have booked in total. Six bookings of one
        person each are six perfectly good bookings.
        """
        for booking in self:
            departure = booking.departure_id
            if booking.pax < 1:
                raise ValidationError(_("A booking needs at least one participant."))
            if booking.pax < departure.min_pax:
                raise ValidationError(_(
                    "This departure takes bookings of at least %(min)s people.",
                    min=departure.min_pax,
                ))
            if booking.pax > departure.max_pax:
                raise ValidationError(_(
                    "This departure takes bookings of at most %(max)s people.",
                    max=departure.max_pax,
                ))

    # --- Lifecycle ---------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        wanted = defaultdict(int)
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("tour.booking") or "/"
            departure = self.env["tour.departure"].browse(vals["departure_id"])
            if "cancellation_policy_id" not in vals:
                vals["cancellation_policy_id"] = departure.tour_id.cancellation_policy_id.id
            # The terms of the sale, taken from the tour once and then this
            # booking's own. An explicit value is left alone, so a desk user can
            # still sell a seat at a price of their choosing.
            if "price_per_person" not in vals:
                vals["price_per_person"] = departure.tour_id.price_per_person
            if "tax_ids" not in vals:
                vals["tax_ids"] = [fields.Command.set(departure.tour_id.tax_ids.ids)]
            # A draft holds its seats exactly like a confirmed booking does.
            if vals.get("state", "draft") in SEAT_HOLDING_STATES:
                wanted[departure.id] += vals.get("pax", 1)

        # Seats are taken here, under the lock, before the rows exist — once per
        # departure, for everything this call is asking of it. Checking each set
        # of values on its own would compare every one of them against the same
        # untouched seat count, since none of them has been written yet, and let
        # a batch of two fours onto a boat with six seats left.
        for departure_id, pax in wanted.items():
            self.env["tour.departure"].browse(departure_id)._lock_and_check(pax)

        bookings = super().create(vals_list)
        for booking in bookings:
            booking._lock_fx_rate()
        bookings.departure_id._sync_full_state()
        return bookings

    # --- Settlement --------------------------------------------------------

    def _lock_fx_rate(self):
        """Fix the rate this booking will be charged at, once.

        Here and not at payment time because this is the moment the guest
        commits: the draft is created the instant they press Book now, and from
        then until the provider redirects them back, the number they were shown
        must not move. Everything after this reads the stored rate.

        Only ever set on a booking that has none. Re-pricing a booking — adding
        a wetsuit at checkout — must not re-quote the rate underneath it.
        """
        self.ensure_one()
        if self.fx_rate:
            return
        settlement = self.settlement_currency_id
        if not settlement or settlement == self.currency_id:
            return
        today = fields.Date.context_today(self)
        self.write({
            "fx_rate": self.company_id._tour_fx_rate(self.currency_id, today),
            "fx_rate_date": today,
        })

    def payment_amount(self):
        """What to charge and in what. -> (float, res.currency).

        The one place that answers this. A provider asked for the settlement
        amount in the settlement currency does no conversion of its own, so the
        figure that comes back in the callback is the figure that went out —
        which is what makes `_record_charged_amount` a check rather than a
        guess.

        A booking with no rate falls back to its own currency rather than to
        zero. That is a booking made before a settlement currency was ever
        configured, and charging it nothing at all would be a far worse answer
        than charging it the amount it has always said it costs.
        """
        self.ensure_one()
        if not self.fx_rate or self.settlement_currency_id == self.currency_id:
            return self.amount_total, self.currency_id
        return self.amount_settlement, self.settlement_currency_id

    def _record_charged_amount(self, transaction):
        """Store what the provider reported taking.

        Normally a formality: the transaction was raised in the settlement
        currency for the exact amount we computed, so the figure that comes back
        is the figure that went out. It is still written down rather than
        assumed, because a refund repays what was actually taken, and "assumed"
        is how a guest gets refunded a number nobody ever charged.

        A discrepancy is therefore an anomaly and is reported as one — on the
        booking so the operator sees it, in the log so it can be found later. It
        does not block the confirmation: the guest has paid, and withholding
        their seats over a rounding difference helps nobody.
        """
        self.ensure_one()
        if not transaction.amount:
            return
        expected, currency = self.payment_amount()
        if transaction.currency_id != currency:
            _logger.warning(
                "Booking %s was charged in %s but expected %s.",
                self.name, transaction.currency_id.name, currency.name,
            )
            self.message_post(body=_(
                "Payment %(reference)s came back in %(paid)s where this booking "
                "is settled in %(expected)s. Nothing was recorded as charged: "
                "check it by hand before refunding anything.",
                reference=transaction.reference,
                paid=transaction.currency_id.name,
                expected=currency.name,
            ))
            return

        if currency.compare_amounts(transaction.amount, expected) != 0:
            _logger.warning(
                "Booking %s asked for %s %s and was charged %s.",
                self.name, expected, currency.name, transaction.amount,
            )
            self.message_post(body=_(
                "Payment %(reference)s took %(charged)s %(currency)s where this "
                "booking asked for %(expected)s. The charged figure is what a "
                "refund repays.",
                reference=transaction.reference,
                charged=transaction.amount,
                currency=currency.name,
                expected=expected,
            ))

        values = {"charged_amount": transaction.amount}
        if self.amount_total:
            values["charged_fx_rate"] = transaction.amount / self.amount_total
        self.write(values)

    def write(self, vals):
        # Growing a party needs the same guarantee as making one, and for the
        # same reason it is asked once per departure rather than once per
        # booking: nothing here has been written yet, so a second booking
        # checked on its own would be measured against a boat the first has not
        # grown on.
        #
        # `ignoring` hands back the seats these bookings already hold, so 2 -> 3
        # asks for one more seat rather than three. Passing the whole recordset
        # is safe: `_lock_and_check` only credits the ones sitting on the
        # departure being checked, so a booking moving in from elsewhere brings
        # no seats with it.
        if "pax" in vals or "departure_id" in vals:
            holding = self.filtered(lambda b: b.state in SEAT_HOLDING_STATES)
            wanted = defaultdict(int)
            for booking in holding:
                departure_id = vals.get("departure_id", booking.departure_id.id)
                wanted[departure_id] += vals.get("pax", booking.pax)
            for departure_id, pax in wanted.items():
                self.env["tour.departure"].browse(departure_id)._lock_and_check(
                    pax, ignoring=holding
                )

        touched = self.departure_id
        result = super().write(vals)
        (touched | self.departure_id)._sync_full_state()
        return result

    def action_confirm(self):
        """Confirm a draft. Does not re-check capacity, and must not.

        The seats were taken at creation and are still held by this very
        booking; checking capacity again here would count them against
        themselves and refuse every confirmation on a departure that just sold
        its last seat to the person now confirming.
        """
        for booking in self:
            if booking.state == "confirmed":
                continue
            if booking.state == "cancelled":
                raise UserError(_("A cancelled booking cannot be confirmed."))
            departure = booking.departure_id
            if departure.state == "cancelled":
                raise UserError(_("This departure has been cancelled."))
            if departure.start_datetime < fields.Datetime.now():
                raise UserError(_("This departure has already run."))
            booking._check_required_answers()
            booking.state = "confirmed"
        return True

    def _check_required_answers(self):
        """Required questions are enforced here rather than at create.

        The checkout builds a booking up over several steps, and a draft that
        cannot be saved until every answer is present is a checkout that cannot
        be built.
        """
        self.ensure_one()
        answered = {(a.question_id.id, a.participant_index) for a in self.answer_ids}
        for question in self.tour_id.question_ids.filtered("required"):
            expected = range(1, self.pax + 1) if question.scope == "per_person" else [0]
            for index in expected:
                if (question.id, index) not in answered:
                    raise UserError(_(
                        "\"%(question)s\" still needs an answer.",
                        question=question.name,
                    ))

    def _can_cancel(self, now=None):
        """May this booking still be cancelled? -> bool."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        return (
            self.state in SEAT_HOLDING_STATES
            and self.departure_id.start_datetime > now
        )

    def action_cancel(self):
        """Cancel, returning the seats and recording what was refundable.

        Refused once the departure has run. Someone opening their booking the
        day after the dive must not be able to trigger a refund calculation at
        all, let alone the full one the widest policy window would hand them.
        """
        now = fields.Datetime.now()
        for booking in self:
            if booking.state == "cancelled":
                continue
            if booking.departure_id.start_datetime <= now:
                raise UserError(_(
                    "This departure has already run, so the booking can no "
                    "longer be cancelled."
                ))
            booking.write({"state": "cancelled", "cancelled_on": now})
        self.departure_id._sync_full_state()
        return True

    # --- The reaper --------------------------------------------------------

    @api.model
    def _cron_release_abandoned_drafts(self):
        """Put the seats of abandoned checkouts back on sale.

        Age alone is not a safe test. An iDEAL payment or a bank transfer can
        settle well after the cutoff, and a reaper that went purely on the clock
        would release those seats, let them be resold, and leave the provider's
        callback confirming a booking against capacity that no longer exists.

        So a draft is only released when nothing suggests its payment is still
        alive: no transaction at all, or every transaction already in a terminal
        failure state.
        """
        cutoff = fields.Datetime.now() - relativedelta(minutes=DRAFT_LIFETIME_MINUTES)
        stale = self.search([("state", "=", "draft"), ("create_date", "<", cutoff)])
        abandoned = stale.filtered(
            lambda b: all(
                tx.state in DEAD_TRANSACTION_STATES for tx in b.transaction_ids
            )
        )
        # No `cancelled_on`: nobody cancelled this, it was never finished. The
        # field means "the guest cancelled", and setting it would invent a
        # refund calculation for a booking that was never paid for.
        abandoned.write({"state": "cancelled"})
        abandoned.departure_id._sync_full_state()
        return abandoned
