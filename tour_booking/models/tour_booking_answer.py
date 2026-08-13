from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TourBookingAnswer(models.Model):
    """One answer to one checkout question.

    `participant_index` is 1-based for a per-person question and 0 for a
    per-booking one. Using 0 rather than null keeps the uniqueness constraint
    below meaningful: in Postgres, NULLs do not collide, so a nullable column
    would let the same booking-level question be answered twice.
    """

    _name = "tour.booking.answer"
    _description = "Booking Answer"
    _order = "question_id, participant_index"

    booking_id = fields.Many2one(
        "tour.booking", required=True, ondelete="cascade", index=True
    )
    question_id = fields.Many2one("tour.question", required=True, ondelete="restrict")
    field_type = fields.Selection(related="question_id.field_type")
    participant_index = fields.Integer(default=0)
    value_char = fields.Char(string="Answer")
    value_bool = fields.Boolean(string="Yes")

    _unique_answer = models.Constraint(
        "UNIQUE(booking_id, question_id, participant_index)",
        "That question has already been answered for that participant.",
    )

    @api.constrains("question_id", "value_char", "participant_index", "booking_id")
    def _check_answer(self):
        for answer in self:
            question = answer.question_id
            if question.field_type == "select":
                if answer.value_char not in question._options():
                    raise ValidationError(_(
                        "\"%(value)s\" is not one of the choices for "
                        "\"%(question)s\".",
                        value=answer.value_char or "",
                        question=question.name,
                    ))
            if question.scope == "per_person":
                if not 1 <= answer.participant_index <= answer.booking_id.pax:
                    raise ValidationError(_(
                        "\"%(question)s\" is asked of each participant, so it "
                        "needs a participant number between 1 and %(pax)s.",
                        question=question.name,
                        pax=answer.booking_id.pax,
                    ))
            elif answer.participant_index:
                raise ValidationError(_(
                    "\"%(question)s\" is asked once per booking, not per "
                    "participant.",
                    question=question.name,
                ))

    def _display_value(self):
        """The answer as text, whatever kind of question it was. -> str."""
        self.ensure_one()
        if self.question_id.field_type == "bool":
            return _("Yes") if self.value_bool else _("No")
        return self.value_char or ""
