from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TourBookingExtra(models.Model):
    """An add-on bought with a booking.

    `unit_price` is copied from the extra rather than related to it, so that
    raising the price of a wetsuit next season does not silently reprice every
    booking ever made.
    """

    _name = "tour.booking.extra"
    _description = "Booking Extra"
    _order = "id"

    booking_id = fields.Many2one(
        "tour.booking", required=True, ondelete="cascade", index=True
    )
    extra_id = fields.Many2one("tour.extra", required=True, ondelete="restrict")
    currency_id = fields.Many2one(related="booking_id.currency_id")
    quantity = fields.Integer(required=True, default=1)
    unit_price = fields.Monetary(required=True, currency_field="currency_id")
    is_taxable = fields.Boolean()
    price_subtotal = fields.Monetary(
        compute="_compute_price_subtotal", store=True, currency_field="currency_id"
    )

    @api.depends("quantity", "unit_price", "extra_id.price_basis", "booking_id.pax")
    def _compute_price_subtotal(self):
        for line in self:
            # A per-person extra is bought for the whole party: one wetsuit each.
            # A per-booking extra is bought once, however many climb into the van.
            multiplier = (
                line.booking_id.pax if line.extra_id.price_basis == "per_person" else 1
            )
            line.price_subtotal = line.unit_price * line.quantity * multiplier

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            extra = self.env["tour.extra"].browse(vals["extra_id"])
            vals.setdefault("unit_price", extra.price)
            vals.setdefault("is_taxable", extra.is_taxable)
        return super().create(vals_list)

    @api.constrains("extra_id", "booking_id")
    def _check_company(self):
        """The tour's own constraint is not the only way in here.

        A line can be made directly — the checkout does exactly that — so the
        currency mismatch has to be refused where the line is written as well
        as where the extra is offered.
        """
        for line in self:
            if line.extra_id.company_id != line.booking_id.company_id:
                raise ValidationError(_(
                    "\"%(extra)s\" belongs to another company than this "
                    "booking and is priced in another currency.",
                    extra=line.extra_id.name,
                ))

    @api.constrains("quantity", "extra_id")
    def _check_quantity(self):
        for line in self:
            if line.quantity < 1:
                raise ValidationError(_("An extra needs a quantity of at least one."))
            limit = line.extra_id.max_quantity
            if limit and line.quantity > limit:
                raise ValidationError(_(
                    "At most %(limit)s of \"%(extra)s\" can be added to a booking.",
                    limit=limit,
                    extra=line.extra_id.name,
                ))
