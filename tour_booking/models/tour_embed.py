import base64

from odoo import _, api, fields, models
from odoo.tools import file_open

# Which widget needs an experience named, and which stands on its own.
NEEDS_TOUR = ("experience", "book")


class TourEmbed(models.TransientModel):
    """The copy-and-paste code for putting a widget on another website.

    A wizard rather than a documentation page because the two things an
    operator gets wrong by hand are the instance's own URL and the database id
    of an experience — and neither is something they should have to know.
    """

    _name = "tour.embed"
    _description = "Website Widget Code"

    widget_type = fields.Selection(
        [
            # Named after what an operator would say they want, not after the
            # route behind it.
            ("experiences", "A page with all your experiences"),
            ("experience", "A page for one experience"),
            ("book", "Just the booking calendar for one experience"),
            ("button", "A Book Now button"),
        ],
        string="Widget",
        required=True,
        default="experiences",
    )
    tour_id = fields.Many2one(
        "tour.tour",
        string="Experience",
        domain=[("is_published", "=", True)],
        help="Only published experiences can be embedded: the widget is served "
             "to the public, and an unpublished one would 404 on somebody "
             "else's page.",
    )
    columns = fields.Selection(
        [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4")],
        default="2",
        help="Cards per row. Pick what fits the column you are pasting into.",
    )
    label = fields.Char(
        string="Button Label",
        default="Book now",
    )
    code = fields.Text(compute="_compute_code", string="Paste this into your site")
    preview_url = fields.Char(compute="_compute_code")
    preview_image = fields.Binary(compute="_compute_preview_image")

    @api.depends("widget_type")
    def _compute_preview_image(self):
        """A picture of what the operator is choosing.

        Read off disk rather than stored, so replacing the file replaces the
        picture — these ship as placeholders and an operator will want their
        own screenshots in them.
        """
        for wizard in self:
            wizard.preview_image = self._widget_picture(wizard.widget_type)

    @api.model
    def _widget_picture(self, widget_type):
        path = "tour_booking/static/src/img/widget_previews/%s.png" % widget_type
        try:
            with file_open(path, "rb", filter_ext=(".png",)) as handle:
                return base64.b64encode(handle.read())
        except (FileNotFoundError, ValueError):
            # A missing picture is a missing picture, not a broken wizard.
            return False

    @api.depends("widget_type", "tour_id", "columns", "label")
    def _compute_code(self):
        """The snippet, and the URL that shows what it will look like.

        Built from `web.base.url` rather than from the request, so the code an
        operator copies points at the address their instance actually answers
        on — not at whatever proxy hostname this page happened to be served
        through.
        """
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        base = (base or "").rstrip("/")
        for wizard in self:
            attributes = ['data-tour-widget="%s"' % wizard.widget_type]
            if wizard.widget_type in NEEDS_TOUR and wizard.tour_id:
                attributes.append('data-tour-id="%s"' % wizard.tour_id.id)
            if wizard.widget_type in ("experiences", "button") and wizard.columns:
                attributes.append('data-tour-columns="%s"' % wizard.columns)
            if wizard.widget_type == "button" and wizard.label:
                attributes.append('data-tour-label="%s"' % wizard.label)

            wizard.code = (
                '<script src="%s/tour/embed.js" async="async"></script>\n'
                "<div %s></div>"
            ) % (base, " ".join(attributes))
            wizard.preview_url = wizard._preview_url(base)

    def _preview_url(self, base):
        """Where the widget lives, so it can be opened and looked at.

        A button has no page of its own — it opens the catalogue — so it
        previews as the catalogue.
        """
        self.ensure_one()
        if self.widget_type in NEEDS_TOUR:
            if not self.tour_id:
                return False
            return "%s/tour/embed/%s/%s" % (base, self.widget_type, self.tour_id.id)
        columns = "?columns=%s" % self.columns if self.columns else ""
        return "%s/tour/embed/experiences%s" % (base, columns)

    @api.model
    def action_open(self, tour_id=None):
        """Open the wizard, on the experience it was asked from if there is one."""
        context = dict(self.env.context)
        if tour_id:
            context.update(default_tour_id=tour_id, default_widget_type="experience")
        return {
            "type": "ir.actions.act_window",
            "name": _("Put this on a website"),
            "res_model": "tour.embed",
            "view_mode": "form",
            "target": "new",
            "context": context,
        }
