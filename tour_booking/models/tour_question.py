from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..const import PRICE_BASIS


class TourQuestion(models.Model):
    """Something the operator needs to know at checkout.

    Shoe size for a wetsuit, dive certification level, dietary requirements,
    which hotel to collect from.

    `scope` reuses the per-person / per-booking split from pricing on purpose:
    shoe size is asked of every participant, hotel name once for the party.
    """

    _name = "tour.question"
    _description = "Checkout Question"
    _order = "sequence, name"

    name = fields.Char(string="Question", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    field_type = fields.Selection(
        [("text", "Text"), ("select", "Choice"), ("bool", "Yes / No")],
        required=True,
        default="text",
    )
    answer_options = fields.Text(
        string="Choices",
        translate=True,
        help="One choice per line. Only used by a Choice question.",
    )
    required = fields.Boolean(default=False)
    scope = fields.Selection(
        PRICE_BASIS,
        string="Asked",
        required=True,
        default="per_booking",
        help="Per person asks it once for each participant.",
    )
    tour_ids = fields.Many2many("tour.tour", string="Tours")

    def _options(self):
        """The choices, parsed. -> list of str.

        Stored as text rather than a model of its own for the same reason the
        tour's content fields are Html: nothing ever queries an option, so a
        model would only add a table and an editor between the operator and a
        list they can type.
        """
        self.ensure_one()
        return [line.strip() for line in (self.answer_options or "").splitlines() if line.strip()]

    @api.constrains("field_type", "answer_options")
    def _check_options(self):
        for question in self:
            if question.field_type == "select" and not question._options():
                raise ValidationError(_(
                    "The question \"%s\" is a choice question but lists no "
                    "choices.", question.name,
                ))
