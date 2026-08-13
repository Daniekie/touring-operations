from odoo import _, api, fields, models
from odoo.addons.base.models.res_partner import _tz_get
from odoo.exceptions import ValidationError


class TourTour(models.Model):
    """The sellable experience: a dive, a boat trip, a day out.

    A tour is not bookable in itself. It describes what happens and what it
    costs; `tour.availability.rule` says when it runs, and those rules
    materialise into `tour.departure` records, which are what actually hold
    seats. Keeping the three apart is what lets an operator change next
    season's schedule without touching the sold departures of this one.
    """

    _name = "tour.tour"
    _description = "Tour"
    _inherit = ["mail.thread", "website.seo.metadata", "website.published.mixin"]
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True, tracking=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")

    description = fields.Html(translate=True, sanitize=False)
    image_1920 = fields.Image(max_width=1920, max_height=1920)
    image_ids = fields.One2many("tour.tour.image", "tour_id")

    duration_hours = fields.Float(
        string="Duration",
        required=True,
        default=2.0,
        help="How long the experience lasts. Shown on the tour card.",
    )
    default_capacity = fields.Integer(
        string="Default Capacity",
        required=True,
        default=10,
        help="Seats on a departure, unless an availability rule overrides it.",
    )
    booking_cutoff_hours = fields.Integer(
        string="Booking Cut-off (hours)",
        default=24,
        help="Stop accepting bookings this many hours before departure. 0 "
             "accepts bookings up to the moment it leaves.",
    )
    has_specific_time = fields.Boolean(
        string="Has Start Times",
        default=True,
        help="Uncheck for a date-only experience with no fixed start time. Its "
             "departures then run from midnight in the tour's timezone.",
    )
    tz = fields.Selection(
        _tz_get,
        string="Timezone",
        required=True,
        default=lambda self: self.env.company.partner_id.tz or "UTC",
        help="The timezone the start times are written in. Departures are "
             "generated months ahead, so without this every departure across a "
             "daylight saving boundary would be an hour out.",
    )

    price_per_person = fields.Monetary(
        required=True, default=0.0, currency_field="currency_id"
    )
    tax_ids = fields.Many2many(
        "account.tax",
        string="Taxes",
        domain=[("type_tax_use", "=", "sale")],
        help="Applied to the tour price and to any extra flagged taxable.",
    )

    # Prose the operator writes once and the site renders verbatim. Deliberately
    # Html rather than one2many lines: nothing ever filters, sorts or shares
    # these between tours, so lines would buy four models and four editors in
    # exchange for making a bullet list harder to write than the wysiwyg already
    # makes it.
    inclusions = fields.Html(string="What's Included", translate=True, sanitize=False)
    exclusions = fields.Html(string="What's Not Included", translate=True, sanitize=False)
    know_before_you_go = fields.Html(translate=True, sanitize=False)
    what_to_bring = fields.Html(translate=True, sanitize=False)

    location_id = fields.Many2one("tour.location", string="Meeting Point")
    meeting_point_note = fields.Text(
        translate=True,
        help="Anything specific to this tour on top of the location's own "
             "directions — 'ask for Marco at the counter'.",
    )

    itinerary_step_ids = fields.One2many("tour.itinerary.step", "tour_id", copy=True)
    start_time_ids = fields.One2many("tour.start.time", "tour_id", copy=True)
    availability_rule_ids = fields.One2many("tour.availability.rule", "tour_id")
    departure_ids = fields.One2many("tour.departure", "tour_id")
    extra_ids = fields.Many2many("tour.extra", string="Extras")
    question_ids = fields.Many2many("tour.question", string="Checkout Questions")

    cancellation_policy_id = fields.Many2one(
        "tour.cancellation.policy",
        string="Cancellation Policy",
        help="Optional. Leave empty to publish no cancellation terms.",
    )

    departure_count = fields.Integer(compute="_compute_counts")
    booking_count = fields.Integer(compute="_compute_counts")
    duration_display = fields.Char(compute="_compute_duration_display")

    @api.depends("duration_hours")
    def _compute_duration_display(self):
        """"3h 30m" for a card. Computed here rather than formatted in QWeb so
        the listing and the detail page cannot drift apart."""
        for tour in self:
            hours = int(tour.duration_hours)
            minutes = round((tour.duration_hours - hours) * 60)
            parts = []
            if hours:
                parts.append(_("%sh", hours))
            if minutes:
                parts.append(_("%smin", minutes))
            tour.duration_display = " ".join(parts) or _("%smin", 0)

    def _compute_counts(self):
        departures = self.env["tour.departure"]._read_group(
            [("tour_id", "in", self.ids)], ["tour_id"], ["__count"]
        )
        bookings = self.env["tour.booking"]._read_group(
            [("tour_id", "in", self.ids), ("state", "!=", "cancelled")],
            ["tour_id"],
            ["__count"],
        )
        departure_map = {tour.id: count for tour, count in departures}
        booking_map = {tour.id: count for tour, count in bookings}
        for tour in self:
            tour.departure_count = departure_map.get(tour.id, 0)
            tour.booking_count = booking_map.get(tour.id, 0)

    @api.depends("name")
    def _compute_website_url(self):
        for tour in self:
            tour.website_url = "/tour/%s" % self.env["ir.http"]._slug(tour)

    @api.constrains("duration_hours", "default_capacity", "booking_cutoff_hours")
    def _check_positive(self):
        for tour in self:
            if tour.duration_hours <= 0:
                raise ValidationError(_("A tour must last longer than zero hours."))
            if tour.default_capacity < 1:
                raise ValidationError(_("A tour needs at least one seat."))
            if tour.booking_cutoff_hours < 0:
                raise ValidationError(_("The booking cut-off cannot be negative."))

    @api.constrains("has_specific_time", "start_time_ids")
    def _check_start_times(self):
        for tour in self:
            if tour.has_specific_time and not tour.start_time_ids:
                raise ValidationError(_(
                    "%s has start times switched on but none defined. Add a "
                    "start time, or turn it into a date-only tour.",
                    tour.name,
                ))

    def action_view_departures(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Departures"),
            "res_model": "tour.departure",
            "view_mode": "list,calendar,form",
            "domain": [("tour_id", "=", self.id)],
            "context": {"default_tour_id": self.id},
        }

    def action_view_bookings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Bookings"),
            "res_model": "tour.booking",
            "view_mode": "list,form",
            "domain": [("tour_id", "=", self.id)],
        }


class TourTourImage(models.Model):
    """A gallery image. Separate from `image_1920` so the tour keeps one
    unambiguous main image for cards and social previews."""

    _name = "tour.tour.image"
    _description = "Tour Image"
    _order = "sequence, id"

    tour_id = fields.Many2one("tour.tour", required=True, ondelete="cascade", index=True)
    name = fields.Char(translate=True, help="Used as the image's alt text.")
    sequence = fields.Integer(default=10)
    image_1920 = fields.Image(max_width=1920, max_height=1920, required=True)
