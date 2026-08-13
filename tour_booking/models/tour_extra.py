from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..const import PRICE_BASIS


class TourExtra(models.Model):
    """A paid add-on: a wetsuit, a snorkel set, hotel pickup.

    One generic model rather than a field per add-on, so an operator can invent
    a new one without a developer. `price_basis` is the only thing that varies
    structurally: a wetsuit is per person, a hotel pickup is per booking however
    many people climb into the van.
    """

    _name = "tour.extra"
    _description = "Tour Extra"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")
    price = fields.Monetary(required=True, currency_field="currency_id")
    price_basis = fields.Selection(PRICE_BASIS, required=True, default="per_person")
    is_taxable = fields.Boolean(
        string="Taxable",
        default=True,
        help="Apply the tour's taxes to this extra.",
    )
    max_quantity = fields.Integer(
        string="Maximum Per Booking",
        default=0,
        help="0 means no limit beyond what the party size allows.",
    )
    tour_ids = fields.Many2many("tour.tour", string="Tours")

    @api.constrains("price", "max_quantity")
    def _check_values(self):
        for extra in self:
            if extra.price < 0:
                raise ValidationError(_("An extra cannot have a negative price."))
            if extra.max_quantity < 0:
                raise ValidationError(_("A maximum quantity cannot be negative."))
