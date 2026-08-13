from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..const import DEAD_TRANSACTION_STATES, SEAT_HOLDING_STATES

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
        "tour.departure", required=True, ondelete="restrict", index=True
    )
    tour_id = fields.Many2one(related="departure_id.tour_id", store=True, index=True)
    start_datetime = fields.Datetime(related="departure_id.start_datetime", store=True)
    partner_id = fields.Many2one("res.partner", string="Guest", required=True, index=True)
    company_id = fields.Many2one(related="departure_id.company_id", store=True)
    currency_id = fields.Many2one(related="departure_id.currency_id")

    pax = fields.Integer(string="Participants", required=True, default=1)
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
    amount_paid = fields.Monetary(compute="_compute_amount_paid", store=True)

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
    refund_amount = fields.Monetary(compute="_compute_refund", store=True)

    # --- Computes ----------------------------------------------------------

    @api.depends(
        "pax",
        "tour_id.price_per_person",
        "tour_id.tax_ids",
        "extra_line_ids.price_subtotal",
        "extra_line_ids.is_taxable",
    )
    def _compute_amounts(self):
        """Price the booking server-side.

        Never read a total from the browser, not even as a cross-check: the only
        number that matters is the one computed here.
        """
        for booking in self:
            taxes = booking.tour_id.tax_ids
            taxable = booking.pax * booking.tour_id.price_per_person
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

    @api.depends("transaction_ids.state", "transaction_ids.amount")
    def _compute_amount_paid(self):
        """What the guest actually handed over, not what was invoiced."""
        for booking in self:
            booking.amount_paid = sum(
                tx.amount for tx in booking.transaction_ids if tx.state == "done"
            )

    @api.depends(
        "cancelled_on",
        "amount_paid",
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
            booking.refund_amount = booking.amount_paid * percent / 100.0

    def _refund_preview(self, when=None):
        """What the guest would get back if they cancelled at `when`. -> float.

        A method and not a field, on purpose: the answer depends on the current
        time, so it has to be recomputed on every page load rather than stored.
        """
        self.ensure_one()
        if not self.cancellation_policy_id or not self._can_cancel():
            return 0.0
        percent = self.cancellation_policy_id._refund_percent_at(
            self.departure_id.start_datetime, when or fields.Datetime.now()
        )
        return self.amount_paid * percent / 100.0

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
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("tour.booking") or "/"
            departure = self.env["tour.departure"].browse(vals["departure_id"])
            if "cancellation_policy_id" not in vals:
                vals["cancellation_policy_id"] = departure.tour_id.cancellation_policy_id.id
            # Seats are taken here, under the lock, before the row exists. A
            # draft holds its seats exactly like a confirmed booking does.
            if vals.get("state", "draft") in SEAT_HOLDING_STATES:
                departure._lock_and_check(vals.get("pax", 1))

        bookings = super().create(vals_list)
        bookings.departure_id._sync_full_state()
        return bookings

    def write(self, vals):
        # Growing a party needs the same guarantee as making one. `ignoring`
        # hands back the seats this booking already holds, so 2 -> 3 asks for
        # one more seat rather than three.
        if "pax" in vals or "departure_id" in vals:
            for booking in self:
                if booking.state not in SEAT_HOLDING_STATES:
                    continue
                departure = self.env["tour.departure"].browse(
                    vals.get("departure_id", booking.departure_id.id)
                )
                departure._lock_and_check(vals.get("pax", booking.pax), ignoring=booking)

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
