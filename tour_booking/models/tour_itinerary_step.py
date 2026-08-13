from odoo import fields, models


class TourItineraryStep(models.Model):
    """One stop on the tour, in order."""

    _name = "tour.itinerary.step"
    _description = "Itinerary Step"
    _order = "sequence, id"

    tour_id = fields.Many2one("tour.tour", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True)
    duration_minutes = fields.Integer(
        string="Duration (minutes)",
        help="How long this step takes. Purely descriptive — the tour's own "
             "duration is what the site advertises.",
    )
