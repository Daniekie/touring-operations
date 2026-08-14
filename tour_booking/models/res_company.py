from odoo import fields, models
from odoo.addons.base.models.res_partner import _tz_get


class ResCompany(models.Model):
    _inherit = "res.company"

    tour_tz = fields.Selection(
        _tz_get,
        string="Tour Timezone",
        required=True,
        default="America/Kralendijk",
        help="The timezone your start times are written in. Departures are "
             "generated months ahead, so this is what keeps a 09:00 tour at "
             "09:00 local on both sides of a daylight saving change.",
    )

    # --- Settlement ---------------------------------------------------------
    #
    # Everything is priced, taxed and accounted for in the company's own
    # currency. This is the currency the *payment provider* settles in, and it
    # exists because we convert rather than letting the provider do it: a
    # transaction raised in the settlement currency for an amount we computed
    # comes back in the same currency for the same amount, so there is nothing
    # for the two sides to disagree about in the callback.
    tour_settlement_currency_id = fields.Many2one(
        "res.currency",
        string="Settlement Currency",
        help="The currency your payment provider charges in. Leave empty when "
             "it charges in your own currency — then nothing is converted at "
             "all, which is one fewer thing that can be wrong.",
    )
    tour_fx_margin = fields.Float(
        string="Exchange Margin (%)",
        digits=(16, 4),
        default=0.0,
        help="Added to the day's rate, upward, when a booking fixes its rate. "
             "The rate on the day of booking is not the rate on the day the "
             "money lands, and this is who carries that drift.",
    )

    tour_embed_domains = fields.Char(
        string="Allowed Embed Domains",
        help="Websites allowed to embed your booking widgets, comma "
             "separated — https://example.com, https://www.example.com. "
             "Leave empty to let any site embed them, which is usually what "
             "you want for a public catalogue.",
    )

    def _tour_fx_rate(self, from_currency, date=None):
        """Settlement currency per unit of `from_currency`. -> float.

        The margin moves the figure UP, never down: the rate on the day of
        booking is not the rate on the day the money settles, and the operator
        should not be the one absorbing that drift.

        The *effective* rate is what comes back — margin included — because it
        is what gets stored on a booking and shown to a guest. Keeping the raw
        rate and the margin apart means something downstream can recombine them
        wrongly, having forgotten which of the two it already applied.

        1.0 when there is nothing to convert, so callers have one code path.
        """
        self.ensure_one()
        settlement = self.tour_settlement_currency_id
        if not settlement or settlement == from_currency:
            return 1.0
        base_rate = self.env["res.currency"]._get_conversion_rate(
            from_currency, settlement, self,
            date or fields.Date.context_today(self),
        )
        return base_rate * (1.0 + self.tour_fx_margin / 100.0)
