from datetime import timedelta

from .common import TourCase


class TestAutoGeneration(TourCase):
    """Saving a schedule is the whole gesture.

    A rule that only becomes bookable once a nightly cron has been round is a
    rule the operator has no way of telling apart from a broken one: the form
    says the tour runs every Monday, and the website says nothing is available.
    These tests hold the calendar to what the form claims, at save time.
    """

    def _rule_by_hand(self, **overrides):
        """A rule saved the way the form saves one — no skip flag."""
        values = {
            "tour_id": self.tour.id,
            "date_from": self.monday,
            "date_to": self.monday + timedelta(days=27),
            "recurrence": "weekly",
            "mon": True,
        }
        values.update(overrides)
        return self.env["tour.availability.rule"].create(values)

    def _departures(self, rule):
        return self.env["tour.departure"].search([("rule_id", "=", rule.id)])

    def _open(self, rule):
        return self._departures(rule).filtered(lambda d: d.state == "open")

    def test_saving_a_rule_fills_the_calendar_without_anything_else(self):
        rule = self._rule_by_hand()

        self.assertEqual(
            len(self._departures(rule)), 8,
            "Four Mondays at two start times were not on the calendar after "
            "the rule was saved.",
        )

    def test_a_rule_with_no_end_date_reaches_the_horizon(self):
        rule = self._rule_by_hand(recurrence="daily", date_to=False)

        self.assertTrue(
            self._departures(rule),
            "An open-ended rule materialised nothing at all.",
        )

    def test_widening_a_rule_adds_the_new_dates(self):
        rule = self._rule_by_hand()

        rule.date_to = self.monday + timedelta(days=34)

        self.assertEqual(
            len(self._departures(rule)), 10,
            "A fifth Monday was added to the rule but not to the calendar.",
        )

    def test_narrowing_a_rule_takes_the_dropped_dates_back_down(self):
        rule = self._rule_by_hand()

        rule.date_to = self.monday + timedelta(days=7)

        self.assertEqual(
            {d.date for d in self._open(rule)},
            {self.monday, self.monday + timedelta(days=7)},
            "Departures beyond the rule's new end date were still on sale.",
        )

    def test_a_booked_departure_survives_its_rule_being_narrowed(self):
        rule = self._rule_by_hand()
        last = max(self._departures(rule), key=lambda d: d.start_datetime)
        self._booking(departure=last, pax=2)

        rule.date_to = self.monday + timedelta(days=7)

        self.assertEqual(
            last.state, "open",
            "Shrinking a schedule cancelled a departure a guest had booked.",
        )

    def test_archiving_a_rule_clears_its_departures(self):
        rule = self._rule_by_hand()

        rule.active = False

        self.assertFalse(
            self._open(rule),
            "An archived rule left its departures open for booking.",
        )

    def test_deleting_a_rule_clears_its_departures(self):
        rule = self._rule_by_hand()
        departures = self._departures(rule)

        rule.unlink()

        self.assertEqual(
            set(departures.mapped("state")), {"cancelled"},
            "Deleting a rule left its departures on sale with nothing behind "
            "them.",
        )

    def test_changing_capacity_does_not_disturb_the_calendar(self):
        """Capacity is copied onto a departure at creation and never rewritten.

        The sync must therefore leave the existing ones exactly as they are —
        including their seat counts, which is what people have booked against.
        """
        rule = self._rule_by_hand()
        before = self._departures(rule)

        rule.capacity = 4

        self.assertEqual(self._departures(rule), before)
        self.assertEqual(
            set(before.mapped("capacity")), {10},
            "Editing a rule rewrote the capacity of departures already on sale.",
        )

    def test_adding_a_start_time_puts_it_on_the_calendar(self):
        rule = self._rule_by_hand()

        self.env["tour.start.time"].create({
            "tour_id": self.tour.id,
            "time_of_day": 18.0,
        })

        self.assertEqual(
            len(self._open(rule)), 12,
            "A third start time was added but no departures appeared at it.",
        )

    def test_removing_a_start_time_takes_its_departures_down(self):
        rule = self._rule_by_hand()

        self.tour.start_time_ids.filtered(lambda s: s.time_of_day == 14.5).unlink()

        self.assertEqual(
            len(self._open(rule)), 4,
            "The 14:30 departures stayed on sale after the start time went.",
        )

    def test_a_bulk_load_can_opt_out(self):
        """One pass at the end beats one per rule when importing a season."""
        rule = self.env["tour.availability.rule"].with_context(
            tour_skip_departure_sync=True
        ).create({
            "tour_id": self.tour.id,
            "date_from": self.monday,
            "date_to": self.monday + timedelta(days=27),
            "recurrence": "weekly",
            "mon": True,
        })

        self.assertFalse(self._departures(rule))

    def test_refreshing_the_calendar_says_what_it_did(self):
        rule = self.env["tour.availability.rule"].with_context(
            tour_skip_departure_sync=True
        ).create({
            "tour_id": self.tour.id,
            "date_from": self.monday,
            "date_to": self.monday + timedelta(days=27),
            "recurrence": "weekly",
            "mon": True,
        })

        action = self.env["tour.departure"].action_refresh_calendar()

        self.assertEqual(action["tag"], "display_notification")
        # Not a count: with demo data loaded there are other rules in the
        # database and this pass materialises those too.
        self.assertIn("new departure", action["params"]["message"])
        self.assertEqual(len(self._departures(rule)), 8)

        idle = self.env["tour.departure"].action_refresh_calendar()

        self.assertIn("up to date", idle["params"]["message"])
