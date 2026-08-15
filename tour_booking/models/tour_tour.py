from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# What the website menu is built from. Writing anything else cannot change the
# menu, so it does not pay for a rebuild.
MENU_FIELDS = ("name", "is_published", "sequence", "active", "company_id")


class TourTour(models.Model):
    """The sellable experience: a dive, a boat trip, a day out.

    A tour is not bookable in itself. It describes what happens and what it
    costs; `tour.availability.rule` says when it runs, and those rules
    materialise into `tour.departure` records, which are what actually hold
    seats. Keeping the three apart is what lets an operator change next
    season's schedule without touching the sold departures of this one.
    """

    _name = "tour.tour"
    _description = "Experience"
    _inherit = ["mail.thread", "website.seo.metadata", "website.published.mixin"]
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True, tracking=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    color = fields.Integer(
        string="Colour",
        help="Colour of this tour on the booking calendar. 0 picks one from "
             "the tour's id, so every tour looks different without anybody "
             "having to choose.",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(related="company_id.currency_id")

    # `sanitize=False` on this and the four prose fields below is deliberate and
    # worth knowing about: whoever can edit an experience can put arbitrary
    # markup — including a <script> tag — on a public page. Only Tour Managers
    # can, and the fields exist to hold an operator's own embedded map or video,
    # which sanitizing would strip. It is an accepted risk rather than an
    # oversight, and the trade is: turning sanitizing on removes the injection
    # route and takes the embeds with it.
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
    # Read from the company rather than stored per tour: an operator runs in one
    # place, and asking the same question on every tour only creates chances to
    # answer it inconsistently. Kept as a field named `tz` so the generator and
    # `_local_start` still have one obvious thing to read.
    tz = fields.Selection(related="company_id.tour_tz", string="Timezone")

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

    # `website_url` comes from the mixin and is the path. This is the whole
    # address, which is what somebody wanting to send it to a guest, paste it
    # into Instagram or simply check the page exists actually needs — a bare
    # `/tour/sunset-3` is not something an operator can do anything with.
    website_full_url = fields.Char(
        string="Page Address",
        compute="_compute_website_url",
        help="The public page for this experience. Odoo writes it; there is "
             "nothing to create in the website editor.",
    )

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
        """The page's path, and its whole address.

        Built from `web.base.url` rather than the request, for the same reason
        the embed wizard does: the address an operator copies has to be the one
        their instance answers on, not the proxy hostname this form happened to
        be served through.

        The slug carries the name, so renaming an experience changes the URL.
        Nothing breaks — the route resolves on the id at the end of the slug, so
        every address ever handed out keeps working — but it is why the form
        shows this rather than an operator writing it down once.
        """
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        base = (base or "").rstrip("/")
        for tour in self:
            # A form being filled in has a `NewId`, which has no page and would
            # slug into something meaningless.
            if not isinstance(tour.id, int):
                tour.website_url = tour.website_full_url = False
                continue
            tour.website_url = "/tour/%s" % self.env["ir.http"]._slug(tour)
            tour.website_full_url = base + tour.website_url

    @api.constrains("duration_hours", "default_capacity", "booking_cutoff_hours")
    def _check_positive(self):
        for tour in self:
            if tour.duration_hours <= 0:
                raise ValidationError(_("A tour must last longer than zero hours."))
            if tour.default_capacity < 1:
                raise ValidationError(_("A tour needs at least one seat."))
            if tour.booking_cutoff_hours < 0:
                raise ValidationError(_("The booking cut-off cannot be negative."))

    @api.constrains("extra_ids", "company_id")
    def _check_extra_companies(self):
        """An extra is priced in its own company's currency.

        `tour.booking.extra` reads its currency from the booking, so a 50 EUR
        extra sold on a USD tour lands on the total as 50 USD — a number
        invented from a foreign price list, with nothing to show a conversion
        was skipped. The two have to agree, or the money is wrong and quiet
        about it.
        """
        for tour in self:
            foreign = tour.extra_ids.filtered(
                lambda extra: extra.company_id != tour.company_id
            )
            if foreign:
                raise ValidationError(_(
                    "%(extras)s belong to another company than %(tour)s and "
                    "are priced in another currency. Make a copy under this "
                    "company instead.",
                    extras=", ".join(foreign.mapped("name")),
                    tour=tour.name,
                ))

    def _is_publishable(self):
        """Whether publishing this tour would produce a page a guest can book.

        The single source of truth for both the constraint below, which refuses
        a publication that cannot work, and `create`, which publishes on its own
        and so has to ask the same question first.
        """
        self.ensure_one()
        return bool(self.start_time_ids) or not self.has_specific_time

    @api.constrains("has_specific_time", "start_time_ids", "is_published")
    def _check_start_times(self):
        """Checked at publication, not at every save.

        A tour is built up over several sittings — name and price first, the
        schedule later — and a rule that refuses the first save until the start
        times exist makes creating a tour a single unskippable form. Publishing
        is the moment it has to be true, because that is when a guest can reach
        it, and a published tour with no start times generates no departures and
        so is an unbookable page.
        """
        for tour in self:
            if tour.is_published and not tour._is_publishable():
                raise ValidationError(_(
                    "%s cannot be published: it has start times switched on but "
                    "none defined. Add a start time, or turn it into a date-only "
                    "tour.",
                    tour.name,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        """Create the record, and say in the chatter that a page now exists.

        Creating an experience creates a website page, and nothing in Odoo says
        so: the page is not in the website editor's page list, there is no
        "create a page" step, and an operator who has not been told goes looking
        for one. The confirmation on the form below is the loud version and is
        gone the moment it is dismissed; this is the copy that is still there
        next month, on the record it belongs to.
        """
        tours = super().create(vals_list)
        for tour, vals in zip(tours, vals_list):
            # Published unless the form said otherwise. An experience is filled
            # in to be sold, so an unpublished one is a step nobody meant to
            # leave undone, and the toggle stays there to take it back down.
            # An explicit value in `vals` is a decision and is left alone —
            # that is what the demo data and the duplicate button pass.
            if "is_published" not in vals and tour._is_publishable():
                tour.is_published = True
            tour.message_post(body=Markup("%s <a href=\"%s\">%s</a>") % (
                _("Website page created:"), tour.website_url, tour.website_full_url,
            ))
        self.env["website.menu"].sudo()._tour_sync()
        return tours

    def write(self, vals):
        result = super().write(vals)
        if any(field in vals for field in MENU_FIELDS):
            self.env["website.menu"].sudo()._tour_sync()
        # Turning start times on or off changes what every rule on this tour
        # asks for: a whole day becomes several slots, or the other way round.
        if "has_specific_time" in vals:
            self.availability_rule_ids._sync_departures()
        return result

    def unlink(self):
        """The entry itself goes with the tour — `tour_id` cascades. This is
        for the numbering of the ones that are left.

        The guard first, because the two `ondelete` rules pull in opposite
        directions on purpose: departures cascade from the tour, bookings
        restrict their departure. Deleting a tour somebody has booked therefore
        reached Postgres and came back as a raw foreign-key error on a screen
        an operator can do nothing with. Archiving is what they want here, and
        this says so.
        """
        # Any booking, cancelled ones included: the restriction is on the row,
        # not on the state, so a tour whose bookings were all cancelled hits
        # exactly the same foreign key.
        booked = self.env["tour.booking"].search([("tour_id", "in", self.ids)], limit=1)
        if booked:
            raise UserError(_(
                "%(tour)s has bookings on it and cannot be deleted. Archive it "
                "instead: it stops being sold and the bookings stay where they "
                "are.",
                tour=booked.tour_id.name,
            ))
        result = super().unlink()
        self.env["website.menu"].sudo()._tour_sync()
        return result

    def action_confirm(self):
        """Save, and say where the page went.

        There is no state to advance — a tour is either published or it is not,
        and that is its own toggle. The button exists so a half-filled form has
        something on it that says what pressing it does, because Odoo saves a
        record before running an object button and the save is the entire
        effect.

        What it returns is the other half. This button is only ever on a record
        that does not exist yet (`invisible="id"`), so reaching here means a page
        was just created, and the one thing an operator cannot find on their own
        is where. Sticky, because a toast that fades in four seconds is not how
        you hand somebody a URL.
        """
        self.ensure_one()
        # `%s` is where `links` is substituted, so the address itself is the
        # clickable part rather than a "click here" sitting next to it.
        message = (
            _("Your page is at %s")
            if self.is_published
            else _("Your page is at %s — it goes live for visitors when you "
                   "publish it.")
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("New tour page created"),
                "message": message,
                "links": [{
                    "label": self.website_full_url,
                    "url": self.website_url,
                }],
                "type": "success",
                "sticky": True,
            },
        }

    def action_share(self):
        """The code for putting this experience on a website.

        On the wizard rather than here so the same screen serves the catalogue
        and the button, which belong to no single tour.
        """
        self.ensure_one()
        return self.env["tour.embed"].action_open(tour_id=self.id)

    def action_view_departures(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Calendar"),
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
    color = fields.Integer(
        string="Colour",
        help="Colour of this tour on the booking calendar. 0 picks one from "
             "the tour's id, so every tour looks different without anybody "
             "having to choose.",
    )
    image_1920 = fields.Image(max_width=1920, max_height=1920, required=True)
