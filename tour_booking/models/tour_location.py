from odoo import fields, models


class TourLocation(models.Model):
    """Where a tour departs from.

    A record rather than a handful of fields on the tour, because an operator
    runs many tours out of two or three fixed points — a dive shop, a marina, a
    hotel lobby. Directions written once are directions maintained once, and
    correcting the walking route should not mean editing eleven tours.
    """

    _name = "tour.location"
    _description = "Tour Location"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    street = fields.Char(translate=True)
    city = fields.Char(translate=True)
    zip = fields.Char()
    country_id = fields.Many2one("res.country")
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    how_to_get_there = fields.Html(
        translate=True,
        help="Directions shown to the guest: where to park, which gate, what "
             "the building looks like.",
    )
    tour_ids = fields.One2many("tour.tour", "location_id")
