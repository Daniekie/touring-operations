from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

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

    # On by default: an operator who publishes a tour means for people to find
    # it, and the alternative is adding every entry by hand and renaming it by
    # hand afterwards. Off is for the operator who has laid out their own menu
    # and does not want it rearranged under them.
    tour_auto_menu = fields.Boolean(
        string="Experiences in the Website Menu",
        default=True,
        help="Keep a Tours menu on the website with one entry per published "
             "experience. Unpublished experiences are left out: their page "
             "answers 404, and a menu entry that 404s is worse than none.",
    )

    tour_embed_domains = fields.Char(
        string="Allowed Embed Domains",
        help="Websites allowed to embed your booking widgets, comma "
             "separated — https://example.com, https://www.example.com. "
             "Leave empty to let any site embed them, which is usually what "
             "you want for a public catalogue.",
    )

    @api.constrains("tour_fx_margin")
    def _check_fx_margin(self):
        """A percentage typed into a settings field, with nothing under it.

        At -100 the rate is zero and every guest is charged nothing; below that
        the charge is negative, which is a refund issued at checkout to
        everybody who books. A modest negative margin is a real choice — an
        operator absorbing a little of the drift themselves — so only the part
        that cannot be meant is refused.
        """
        for company in self:
            if company.tour_fx_margin <= -100.0:
                raise ValidationError(_(
                    "An exchange margin of %(margin)s%% would charge guests "
                    "nothing at all, or less.",
                    margin=company.tour_fx_margin,
                ))

    def write(self, vals):
        """Switching the menu setting rebuilds the menu there and then.

        Otherwise the change appears to have done nothing until the next time
        somebody touches a tour, which reads as a broken setting.
        """
        result = super().write(vals)
        if "tour_auto_menu" in vals:
            self.env["website.menu"].sudo()._tour_sync()
        return result

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
