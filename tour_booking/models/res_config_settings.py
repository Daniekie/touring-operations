from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # One operator runs in one place, so the timezone is a property of the
    # business rather than of each tour. Asking for it on every tour was asking
    # the same question over and over and inviting one of the answers to be
    # wrong — which, for a field that decides what time a boat leaves, is the
    # kind of wrong that puts people on a dock at the wrong hour.
    tour_tz = fields.Selection(
        related="company_id.tour_tz",
        string="Tour Timezone",
        readonly=False,
    )
