from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TourStartTime(models.Model):
    """A time of day the tour departs, in the tour's own timezone.

    Stored as a float (9.5 is 09:30) to match Odoo's `float_time` widget, which
    is what every other duration and time-of-day field in the system uses.
    """

    _name = "tour.start.time"
    _description = "Tour Start Time"
    _order = "time_of_day"

    tour_id = fields.Many2one("tour.tour", required=True, ondelete="cascade", index=True)
    time_of_day = fields.Float(string="Start Time", required=True)

    _unique_per_tour = models.Constraint(
        "UNIQUE(tour_id, time_of_day)",
        "A tour cannot have the same start time twice.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Adding an 18:00 sailing puts 18:00 on the calendar straight away."""
        start_times = super().create(vals_list)
        start_times.tour_id.availability_rule_ids._sync_departures()
        return start_times

    def unlink(self):
        """Dropping a start time takes its unsold departures down with it."""
        rules = self.tour_id.availability_rule_ids
        result = super().unlink()
        rules._sync_departures()
        return result

    @api.constrains("time_of_day")
    def _check_within_the_day(self):
        for start_time in self:
            if not 0.0 <= start_time.time_of_day < 24.0:
                raise ValidationError(_("A start time must fall within the day."))

    @api.depends("time_of_day")
    def _compute_display_name(self):
        for start_time in self:
            hours = int(start_time.time_of_day)
            minutes = round((start_time.time_of_day - hours) * 60)
            start_time.display_name = "%02d:%02d" % (hours, minutes)
