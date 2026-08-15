import pytz

from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Field name per weekday, indexed by `date.weekday()`.
WEEKDAY_FIELDS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Writing one of these changes *which* departures the rule implies, so the
# calendar has to be rebuilt. Capacity and party sizes are deliberately absent:
# they are copied onto a departure when it is created and never rewritten
# afterwards (see `tour.departure._generate`), so changing them moves nothing.
SLOT_FIELDS = [
    "active",
    "date_from",
    "date_to",
    "recurrence",
    "all_start_times",
    "start_time_ids",
    *WEEKDAY_FIELDS,
]

# Suppresses the sync below. For bulk loads, where one pass at the end is
# cheaper than one per rule, and for the generator's own tests, which drive
# `_generate` directly with a horizon of their choosing.
SKIP_SYNC = "tour_skip_departure_sync"


class TourAvailabilityRule(models.Model):
    """A recurring pattern that says when a tour runs.

    A rule is a statement of intent, not inventory. It generates
    `tour.departure` records, and once generated those live their own life: an
    operator who cancels one Tuesday has cancelled that Tuesday, and editing the
    rule afterwards must not resurrect it. See `tour.departure._generate`.
    """

    _name = "tour.availability.rule"
    _description = "Availability Rule"
    _order = "date_from, id"

    tour_id = fields.Many2one("tour.tour", required=True, ondelete="cascade", index=True)
    active = fields.Boolean(default=True)
    internal_label = fields.Char(
        string="Label",
        help="Admin-facing only, never shown to a guest. 'High season', "
             "'Sundays only'.",
    )

    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date(
        help="Leave empty to keep generating departures indefinitely.",
    )

    recurrence = fields.Selection(
        [
            ("daily", "Every day"),
            ("weekly", "Selected weekdays"),
            ("one_off", "One-off date"),
        ],
        required=True,
        default="weekly",
    )
    mon = fields.Boolean("Monday")
    tue = fields.Boolean("Tuesday")
    wed = fields.Boolean("Wednesday")
    thu = fields.Boolean("Thursday")
    fri = fields.Boolean("Friday")
    sat = fields.Boolean("Saturday")
    sun = fields.Boolean("Sunday")

    min_pax = fields.Integer(
        string="Minimum Party Size",
        required=True,
        default=1,
        help="The smallest booking accepted. This is a limit on one booking, "
             "not a threshold the departure has to reach to run.",
    )
    max_pax = fields.Integer(
        string="Maximum Party Size",
        required=True,
        default=10,
        help="The largest single booking accepted. It does not cap the "
             "departure: capacity does that.",
    )
    capacity = fields.Integer(
        help="Seats on the departures this rule generates. 0 uses the tour's "
             "default capacity.",
    )

    all_start_times = fields.Boolean(
        string="All Start Times", default=True,
        help="Generate a departure for every start time the tour offers.",
    )
    start_time_ids = fields.Many2many(
        "tour.start.time",
        string="Start Times",
        help="Used only when 'All Start Times' is off.",
    )

    departure_ids = fields.One2many("tour.departure", "rule_id")

    @api.model_create_multi
    def create(self, vals_list):
        rules = super().create(vals_list)
        rules._sync_departures()
        return rules

    def write(self, vals):
        result = super().write(vals)
        if any(field in vals for field in SLOT_FIELDS):
            self._sync_departures()
        return result

    def unlink(self):
        # Read the departures while the link still exists: `rule_id` is
        # `ondelete="set null"`, so after the delete nothing connects them back
        # to the rule that is going away.
        stranded = self.departure_ids
        result = super().unlink()
        stranded = stranded.exists()
        stranded._retire_orphans(within=stranded)
        return result

    def _sync_departures(self):
        """Bring the calendar in line with these rules.

        The whole point of doing this on save rather than leaving it to the
        nightly cron: a rule that has not been materialised yet is a schedule
        that exists in the database and nowhere else. The website shows no
        availability, the calendar is empty, and there is nothing on screen to
        tell an operator that from a bug — the fix was a menu item they had no
        reason to know about.

        Both directions, because both are the same mistake seen from either
        end: a rule that has just been widened owes the calendar departures, and
        one that has just been narrowed owes it the removal of departures it no
        longer stands behind.
        """
        if self.env.context.get(SKIP_SYNC) or self.env.context.get("install_mode"):
            return
        departures = self.env["tour.departure"]
        live = self.filtered("active")
        if live:
            departures._generate(rules=live)
        # After generating, so that a rule which merely moved its start times
        # has the new departures in place before the old ones are retired.
        departures._retire_orphans(within=self.departure_ids)

    @api.constrains("date_from", "date_to", "recurrence", *WEEKDAY_FIELDS)
    def _check_dates(self):
        for rule in self:
            if rule.date_to and rule.date_to < rule.date_from:
                raise ValidationError(_("A rule cannot end before it starts."))
            if rule.recurrence == "weekly" and not rule._weekdays():
                raise ValidationError(_(
                    "A weekly rule needs at least one weekday selected."
                ))

    @api.constrains("min_pax", "max_pax", "capacity")
    def _check_party_size(self):
        for rule in self:
            if rule.min_pax < 1:
                raise ValidationError(_("The minimum party size must be at least 1."))
            if rule.max_pax < rule.min_pax:
                raise ValidationError(_(
                    "The maximum party size cannot be below the minimum."
                ))
            if rule.capacity < 0:
                raise ValidationError(_("Capacity cannot be negative."))

    @api.onchange("recurrence")
    def _onchange_recurrence(self):
        # A one-off runs on exactly one day, so its end date is not a separate
        # decision the operator should be asked to make.
        if self.recurrence == "one_off":
            self.date_to = self.date_from

    @api.onchange("date_from")
    def _onchange_date_from(self):
        if self.recurrence == "one_off":
            self.date_to = self.date_from

    def _weekdays(self):
        """The weekday indexes this rule fires on. -> set of int (Mon=0)."""
        self.ensure_one()
        return {i for i, name in enumerate(WEEKDAY_FIELDS) if self[name]}

    def _effective_capacity(self):
        self.ensure_one()
        return self.capacity or self.tour_id.default_capacity

    def _times_of_day(self):
        """The start times this rule generates. -> list of float.

        A date-only tour yields a single midnight slot, so that every departure
        has exactly one `start_datetime` and nothing downstream has to special
        case the absence of a time.
        """
        self.ensure_one()
        if not self.tour_id.has_specific_time:
            return [0.0]
        times = self.tour_id.start_time_ids if self.all_start_times else self.start_time_ids
        return sorted(times.mapped("time_of_day"))

    def _dates(self, horizon_end):
        """The dates this rule fires on, up to `horizon_end`. -> iterator of date."""
        self.ensure_one()
        last = min(self.date_to, horizon_end) if self.date_to else horizon_end
        if self.recurrence == "one_off":
            if self.date_from <= last:
                yield self.date_from
            return
        weekdays = self._weekdays() if self.recurrence == "weekly" else set(range(7))
        day = self.date_from
        while day <= last:
            if day.weekday() in weekdays:
                yield day
            day += timedelta(days=1)

    def _covers(self, day):
        """Does this rule fire on `day`? -> bool."""
        self.ensure_one()
        if day < self.date_from or (self.date_to and day > self.date_to):
            return False
        if self.recurrence == "one_off":
            return day == self.date_from
        if self.recurrence == "weekly":
            return day.weekday() in self._weekdays()
        return True

    def _slots_for_day(self, day):
        """The departures this rule implies on one day. -> list of dicts.

        The datetime is built in the tour's timezone and converted to UTC here
        rather than at read time. Departures are generated a year ahead and so
        cross a daylight saving boundary; an 09:00 dive has to stay 09:00 local
        on both sides of it.
        """
        self.ensure_one()
        if not self._covers(day):
            return []
        tz = pytz.timezone(self.tour_id.tz or "UTC")
        capacity = self._effective_capacity()
        slots = []
        for time_of_day in self._times_of_day():
            hours = int(time_of_day)
            minutes = round((time_of_day - hours) * 60)
            local = tz.localize(datetime.combine(day, time(hours, minutes)))
            slots.append({
                "tour_id": self.tour_id.id,
                "rule_id": self.id,
                "date": day,
                "start_datetime": local.astimezone(pytz.utc).replace(tzinfo=None),
                "capacity": capacity,
                "min_pax": self.min_pax,
                "max_pax": self.max_pax,
            })
        return slots

    def _slots(self, horizon_end):
        """Every departure this rule implies up to `horizon_end`. -> list of dicts."""
        self.ensure_one()
        slots = []
        for day in self._dates(horizon_end):
            slots.extend(self._slots_for_day(day))
        return slots
