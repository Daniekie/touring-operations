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
