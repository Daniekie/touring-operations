from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TourCancellationPolicy(models.Model):
    """What a guest gets back, and when.

    Optional on a tour: an operator who does not want to publish terms should
    not be forced through this model to save a tour.

    The policy is a set of windows measured backwards from departure. A booking
    cancelled 50 hours out, against windows of 48h/100% and 24h/50%, falls in
    the 48-hour window and is refunded in full.
    """

    _name = "tour.cancellation.policy"
    _description = "Cancellation Policy"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    description = fields.Html(
        translate=True,
        help="Shown to the guest on the tour page and on their booking.",
    )
    rule_ids = fields.One2many("tour.cancellation.rule", "policy_id", copy=True)
    tour_ids = fields.One2many("tour.tour", "cancellation_policy_id")

    def _refund_percent_at(self, start_datetime, when):
        """What a cancellation at `when` would be refunded. -> float 0..100.

        Deliberately a method taking an explicit moment rather than a field.
        The figure a guest sees before deciding depends on the current time, and
        a stored field computed from `now()` would freeze at whatever value it
        held when the row was last written and then quietly lie for the rest of
        the booking's life. The controller passes `fields.Datetime.now()`; the
        booking passes its own `cancelled_on`.
        """
        self.ensure_one()
        if not start_datetime or not when:
            return 0.0
        hours_out = (start_datetime - when).total_seconds() / 3600.0
        # Widest window first. A rule reads "cancel at least N hours ahead and
        # get P%", so the guest earns the most generous window they are still
        # early enough for: 50 hours out, against 48h/100% and 24h/50%, is 100%.
        for rule in self.rule_ids.sorted("hours_before", reverse=True):
            if hours_out >= rule.hours_before:
                return rule.refund_percent
        # Too close to departure for any window, including a 0-hour one if the
        # policy defines it. Nothing back.
        return 0.0


class TourCancellationRule(models.Model):
    """One refund window of a policy."""

    _name = "tour.cancellation.rule"
    _description = "Cancellation Rule"
    _order = "hours_before desc, id"

    policy_id = fields.Many2one(
        "tour.cancellation.policy", required=True, ondelete="cascade", index=True
    )
    hours_before = fields.Integer(
        string="Hours Before Departure",
        required=True,
        help="Cancel at least this many hours before departure to get the "
             "refund below. 48 means two days.",
    )
    refund_percent = fields.Float(
        string="Refund %",
        required=True,
        help="0 means no refund, 100 means the full amount.",
    )

    @api.constrains("hours_before", "refund_percent")
    def _check_bounds(self):
        for rule in self:
            if rule.hours_before < 0:
                raise ValidationError(_("Hours before departure cannot be negative."))
            if not 0.0 <= rule.refund_percent <= 100.0:
                raise ValidationError(_("A refund percentage must be between 0 and 100."))
