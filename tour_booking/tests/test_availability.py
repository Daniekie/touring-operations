from datetime import date, datetime, timedelta

from odoo import fields

from .common import TourCase


class TestAvailability(TourCase):
    """Rules describe intent; departures are the inventory that intent creates."""

    def test_a_weekly_rule_generates_departures_on_the_selected_weekdays(self):
        rule = self._rule(mon=True, wed=True)
        departures = self._generate(rule)

        # Four Mondays and four Wednesdays in the 28-day window, two start times
        # on each of those days.
        self.assertEqual(len(departures), 16)
        self.assertEqual(
            {d.date.weekday() for d in departures},
            {0, 2},
            "A weekly rule generated departures on weekdays it was not asked for.",
        )

    def test_a_daily_rule_covers_every_day_in_its_range(self):
        rule = self._rule(recurrence="daily", date_to=self.monday + timedelta(days=6))
        departures = self._generate(rule, self.monday + timedelta(days=6))

        self.assertEqual(len(departures), 14, "Seven days at two start times each.")

    def test_a_one_off_rule_generates_a_single_day(self):
        rule = self._rule(recurrence="one_off", date_to=self.monday)
        departures = self._generate(rule)

        self.assertEqual(len(departures), 2, "One day, two start times.")
        self.assertEqual(departures.mapped("date"), [self.monday, self.monday])

    def test_a_date_only_tour_generates_one_departure_per_day(self):
        """A tour with no start time still gets exactly one departure a day.

        Making the absence of a time mean "no departure" would be a special case
        every consumer downstream would have to know about; midnight local is
        one, and it is invisible to the guest.
        """
        self.tour.start_time_ids.unlink()
        self.tour.has_specific_time = False
        rule = self._rule()

        departures = self._generate(rule)

        self.assertEqual(len(departures), 4, "Four Mondays, one departure each.")

    def test_regenerating_does_not_duplicate_departures(self):
        rule = self._rule()
        first = self._generate(rule)
        self.assertEqual(len(first), 8)

        second = self._generate(rule)

        self.assertFalse(second, "The second run created departures that already existed.")
        self.assertEqual(
            self.env["tour.departure"].search_count([("rule_id", "=", rule.id)]),
            8,
            "Running the generator twice doubled the inventory.",
        )

    def test_a_manual_capacity_change_survives_regeneration(self):
        rule = self._rule()
        departures = self._generate(rule)
        adjusted = departures[0]
        adjusted.capacity = 4

        self._generate(rule)

        self.assertEqual(
            adjusted.capacity, 4,
            "Regeneration overwrote a capacity somebody had set by hand.",
        )
        self.assertTrue(adjusted.is_manually_adjusted)

    def test_a_manually_cancelled_departure_is_not_reopened(self):
        rule = self._rule()
        departures = self._generate(rule)
        cancelled = departures[0]
        cancelled.action_cancel()

        self._generate(rule)

        self.assertEqual(
            cancelled.state, "cancelled",
            "Regeneration resurrected a departure the operator had cancelled.",
        )

    def test_departures_are_generated_in_the_tours_timezone_across_a_dst_boundary(self):
        """09:00 local stays 09:00 local on both sides of the clock change.

        Europe/Amsterdam moves to summer time on 28 March 2027. A generator that
        worked in UTC, or that computed one offset and reused it, would put every
        departure after that date an hour out — and the guests would arrive to
        find the boat gone.
        """
        rule = self._rule(
            recurrence="daily",
            date_from=date(2027, 3, 27),
            date_to=date(2027, 3, 29),
        )

        departures = self._generate(rule, date(2027, 3, 29))
        at_nine = departures.filtered(lambda d: d.start_datetime.minute == 0)
        by_date = {d.date: d.start_datetime for d in at_nine}

        self.assertEqual(
            by_date[date(2027, 3, 27)], datetime(2027, 3, 27, 8, 0),
            "Winter time: 09:00 in Amsterdam is 08:00 UTC.",
        )
        self.assertEqual(
            by_date[date(2027, 3, 29)], datetime(2027, 3, 29, 7, 0),
            "Summer time: 09:00 in Amsterdam is 07:00 UTC.",
        )

    def test_the_timezone_comes_from_the_company_not_the_tour(self):
        """One operator, one timezone, asked once.

        It was a required field on every tour, which was the same question over
        and over with a fresh chance to answer it wrong each time — and for a
        field that decides what time a boat leaves, wrong means guests on a dock
        at the wrong hour.
        """
        self.env.company.tour_tz = "America/Kralendijk"
        rule = self._rule(recurrence="one_off", date_to=self.monday)

        departures = self._generate(rule)

        self.assertEqual(self.tour.tz, "America/Kralendijk")
        self.assertEqual(
            departures[0].start_datetime, datetime(2027, 3, 1, 13, 0),
            "09:00 on Bonaire is 13:00 UTC; the company setting must drive it.",
        )

    def test_changing_the_company_timezone_moves_future_generation(self):
        """Departures already generated keep the time they were sold at — the
        generator never rewrites an existing row — but new ones follow the new
        setting."""
        self.env.company.tour_tz = "America/Kralendijk"
        first = self._generate(self._rule(recurrence="one_off", date_to=self.monday))

        self.env.company.tour_tz = "Europe/Amsterdam"
        later = self.monday + timedelta(days=7)
        second = self._generate(
            self._rule(recurrence="one_off", date_from=later, date_to=later), later
        )

        self.assertEqual(first[0].start_datetime, datetime(2027, 3, 1, 13, 0))
        self.assertEqual(second[0].start_datetime, datetime(2027, 3, 8, 8, 0))

    def test_a_rule_with_no_end_date_generates_up_to_the_horizon(self):
        rule = self._rule(date_to=False)

        departures = self._generate(rule, self.monday + timedelta(days=13))

        self.assertEqual(len(departures), 4, "Two Mondays, two start times each.")

    def test_a_rule_can_be_limited_to_some_of_the_tours_start_times(self):
        morning = self.tour.start_time_ids.filtered(lambda t: t.time_of_day == 9.0)
        rule = self._rule(all_start_times=False, start_time_ids=[(6, 0, morning.ids)])

        departures = self._generate(rule)

        self.assertEqual(len(departures), 4, "Four Mondays, morning only.")

    def test_a_departure_whose_rule_no_longer_covers_it_is_cancelled(self):
        rule = self._rule()
        departures = self._generate(rule)
        self.assertEqual(len(departures), 8)

        # The operator shortens the season to its first week.
        rule.date_to = self.monday
        self.env["tour.departure"]._retire_orphans()

        still_open = departures.filtered(lambda d: d.state == "open")
        self.assertEqual(
            len(still_open), 2,
            "Only the first Monday's two departures are still covered by the rule.",
        )

    def test_a_departure_with_a_booking_is_never_retired(self):
        """A stale row on a calendar is a nuisance; deleting a departure someone
        has paid for is a disaster. The generator is not allowed to make that
        trade."""
        rule = self._rule()
        departures = self._generate(rule)
        sold = departures[-1]
        self._booking(departure=sold, pax=2)

        rule.date_to = self.monday
        self.env["tour.departure"]._retire_orphans()

        self.assertNotEqual(
            sold.state, "cancelled",
            "A departure with a booking on it was retired by the generator.",
        )

    def test_past_departures_are_marked_done(self):
        past = self._departure(start_datetime=fields.Datetime.now() - timedelta(days=1))

        self.env["tour.departure"]._close_past()

        self.assertEqual(past.state, "done")
        self.assertFalse(
            past.is_manually_adjusted,
            "Closing a past departure is housekeeping, not a manual adjustment.",
        )
