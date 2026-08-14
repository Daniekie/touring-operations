from datetime import date, datetime, timedelta

from odoo import fields
from odoo.exceptions import UserError

from odoo.addons.tour_booking.models.tour_departure import MAX_GRID_DAYS

from .common import TourCase


class TestCalendarGrid(TourCase):
    """The data behind the Booking Calendar.

    Worth testing hard in Python, because the component that draws it cannot be
    tested here at all: rows, columns, counts and filters are all decided on
    this side, and only the drawing happens in the browser.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A fixed week, so "this week" never straddles a month boundary mid-run.
        cls.week_from = date(2027, 3, 1)     # Monday
        cls.week_to = date(2027, 3, 7)       # Sunday

        # The grid is deliberately global — it shows every tour's trips — so
        # these tests have to start from an empty schedule. Demo data is loaded
        # in the test database and its open-ended rules generate a year ahead,
        # which lands two dozen departures squarely in the week below.
        #
        # The demo bookings go first: `tour.booking.departure_id` is
        # `ondelete="restrict"`, on purpose, so a sold departure cannot be
        # deleted out from under a guest.
        cls.env["tour.booking"].search([]).unlink()
        cls.env["tour.departure"].search([]).unlink()

    def _grid(self, **kwargs):
        return self.env["tour.departure"].get_calendar_grid(
            kwargs.pop("date_from", self.week_from),
            kwargs.pop("date_to", self.week_to),
            **kwargs,
        )

    def _at(self, day, hour, minute=0, tour=None, capacity=15):
        """A departure at a local wall-clock time on `day`."""
        tour = tour or self.tour
        # The fixtures run in Europe/Amsterdam, which in early March is UTC+1.
        return self.env["tour.departure"].create({
            "tour_id": tour.id,
            "date": day,
            "start_datetime": datetime(day.year, day.month, day.day, hour - 1, minute),
            "capacity": capacity,
            "min_pax": 1,
            "max_pax": 6,
        })

    # --- Shape --------------------------------------------------------------

    def test_a_range_wider_than_the_screen_can_use_is_refused(self):
        """The method is callable from the browser, and it read whatever range
        it was handed.

        Eleven years of departures took 411ms and thirty-one queries on a
        database of eighteen thousand — one worker, one request, and nothing
        between a mistyped URL and the whole table. The component never asks for
        more than a few weeks.
        """
        with self.assertRaises(UserError):
            self._grid(date_from=date(2020, 1, 1), date_to=date(2030, 12, 31))

    def test_the_widest_range_the_cap_allows_is_accepted(self):
        """The screen asks for a week; the cap is six, so there is room for a
        month view later. Either way the boundary itself has to work."""
        grid = self._grid(
            date_from=self.week_from,
            date_to=self.week_from + timedelta(days=MAX_GRID_DAYS - 1),
        )

        self.assertEqual(len(grid["days"]), MAX_GRID_DAYS)

    def test_a_backwards_range_is_refused_rather_than_drawn_empty(self):
        with self.assertRaises(UserError):
            self._grid(date_from=self.week_to, date_to=self.week_from)

    def test_the_grid_covers_every_day_of_the_week(self):
        grid = self._grid()

        self.assertEqual(len(grid["days"]), 7)
        self.assertEqual(grid["days"][0]["date"], "2027-03-01")
        self.assertEqual(grid["days"][0]["weekday"], "Mon")
        self.assertEqual(grid["days"][-1]["date"], "2027-03-07")

    def test_rows_are_start_times_and_columns_are_days(self):
        """The whole point of the layout: one row per departure time, read
        across the week."""
        monday = self._at(self.week_from, 9)
        tuesday = self._at(self.week_from + timedelta(days=1), 9)
        afternoon = self._at(self.week_from, 14)

        grid = self._grid()

        rows = {row["label"]: row for row in grid["rows"]}
        self.assertEqual(set(rows), {"09:00", "14:00"})
        self.assertEqual(
            [cell["id"] for cell in rows["09:00"]["cells"]["2027-03-01"]], [monday.id]
        )
        self.assertEqual(
            [cell["id"] for cell in rows["09:00"]["cells"]["2027-03-02"]], [tuesday.id]
        )
        self.assertEqual(
            [cell["id"] for cell in rows["14:00"]["cells"]["2027-03-01"]], [afternoon.id]
        )

    def test_rows_are_ordered_by_time_of_day(self):
        self._at(self.week_from, 16)
        self._at(self.week_from, 9)
        self._at(self.week_from, 14)

        grid = self._grid()

        self.assertEqual([row["label"] for row in grid["rows"]], ["09:00", "14:00", "16:00"])

    def test_a_cell_carries_the_seats_sold_and_the_capacity(self):
        """The "0 / 15" on each card, which is the number the operator is
        actually scanning for."""
        departure = self._at(self.week_from, 9, capacity=15)
        self._booking(departure=departure, pax=4)

        cell = self._grid()["rows"][0]["cells"]["2027-03-01"][0]

        self.assertEqual(cell["seats_sold"], 4)
        self.assertEqual(cell["capacity"], 15)
        self.assertEqual(cell["tour_name"], self.tour.name)

    def test_times_are_shown_in_the_tours_timezone(self):
        """Stored UTC, displayed local — the same rule the website follows."""
        self._at(self.week_from, 9)

        grid = self._grid()

        self.assertEqual(grid["rows"][0]["label"], "09:00")
        self.assertEqual(grid["rows"][0]["cells"]["2027-03-01"][0]["time"], "09:00")

    def test_two_tours_at_the_same_time_share_a_row(self):
        other = self.env["tour.tour"].create({
            "name": "Reef Snorkel",
            "duration_hours": 2.0,
            "default_capacity": 8,
            "price_per_person": 30.0,
            "start_time_ids": [(0, 0, {"time_of_day": 9.0})],
        })
        self._at(self.week_from, 9)
        self._at(self.week_from, 9, tour=other)

        grid = self._grid()

        self.assertEqual(len(grid["rows"]), 1)
        self.assertEqual(len(grid["rows"][0]["cells"]["2027-03-01"]), 2)

    def test_a_tours_colour_is_stable_and_can_be_chosen(self):
        """A tour keeps one colour across the week, so a row reads as one thing.

        Deliberately not asserting that two tours always differ: the palette has
        eleven entries, so an operator with a dozen tours will see a repeat. That
        is what the `color` field is for — the default is only a decent guess
        that nobody has to make.
        """
        chosen = self.env["tour.tour"].create({
            "name": "Reef Snorkel",
            "duration_hours": 2.0,
            "default_capacity": 8,
            "price_per_person": 30.0,
            "color": 7,
            "start_time_ids": [(0, 0, {"time_of_day": 9.0})],
        })
        self._at(self.week_from, 9, tour=chosen)
        self._at(self.week_from + timedelta(days=1), 14, tour=chosen)
        self._at(self.week_from, 9)

        grid = self._grid()

        colors = {
            cell["tour_id"]: cell["color"]
            for row in grid["rows"]
            for cells in row["cells"].values()
            for cell in cells
        }
        self.assertEqual(colors[chosen.id], 7, "An explicit colour must win.")
        self.assertEqual(
            colors[self.tour.id], self.tour.id % 11,
            "Without one, the colour is derived from the tour so it never moves.",
        )

    # --- Grouping by experience --------------------------------------------

    def test_by_experience_groups_the_rows_by_tour(self):
        other = self.env["tour.tour"].create({
            "name": "Reef Snorkel",
            "duration_hours": 2.0,
            "default_capacity": 8,
            "price_per_person": 30.0,
            "start_time_ids": [(0, 0, {"time_of_day": 9.0})],
        })
        self._at(self.week_from, 9)
        self._at(self.week_from, 14)
        self._at(self.week_from, 9, tour=other)

        grid = self._grid(mode="experience")

        labels = [row["label"] for row in grid["rows"]]
        self.assertEqual(set(labels), {self.tour.name, other.name})
        by_label = {row["label"]: row for row in grid["rows"]}
        self.assertEqual(
            len(by_label[self.tour.name]["cells"]["2027-03-01"]), 2,
            "Both of that tour's times belong to its own row.",
        )

    # --- Stats and filters --------------------------------------------------

    def test_the_header_counts_departures_sold_out_and_closed_out(self):
        self._at(self.week_from, 9, capacity=15)
        sold_out = self._at(self.week_from, 14, capacity=2)
        self._booking(departure=sold_out, pax=2)
        cancelled = self._at(self.week_from, 16)
        cancelled.action_cancel()

        stats = self._grid()["stats"]

        self.assertEqual(stats["departures"], 3)
        self.assertEqual(stats["sold_out"], 1)
        self.assertEqual(stats["closed_out"], 1)

    def test_a_cancelled_trip_with_guests_on_it_needs_attention(self):
        """The one number on that bar that is a job rather than a fact: those
        guests have to be told."""
        cancelled = self._at(self.week_from, 9)
        self._booking(departure=cancelled, pax=2)
        cancelled.action_cancel()
        quietly_cancelled = self._at(self.week_from, 14)
        quietly_cancelled.action_cancel()

        stats = self._grid()["stats"]

        self.assertEqual(stats["closed_out"], 2)
        self.assertEqual(
            stats["need_attention"], 1,
            "Only the cancelled trip that somebody had booked is a problem.",
        )

    def test_only_booked_hides_empty_departures(self):
        booked = self._at(self.week_from, 9)
        self._booking(departure=booked, pax=1)
        self._at(self.week_from, 14)

        grid = self._grid(show="booked")

        self.assertEqual(len(grid["rows"]), 1)
        self.assertEqual(grid["rows"][0]["label"], "09:00")

    def test_only_disrupted_shows_cancelled_departures(self):
        self._at(self.week_from, 9)
        cancelled = self._at(self.week_from, 14)
        cancelled.action_cancel()

        grid = self._grid(show="disrupted")

        self.assertEqual(len(grid["rows"]), 1)
        self.assertEqual(grid["rows"][0]["cells"]["2027-03-01"][0]["state"], "cancelled")

    def test_the_counts_ignore_the_filter(self):
        """The header describes the week, not the current view of it. A filter
        that changed the totals would make "0 sold out" mean nothing."""
        booked = self._at(self.week_from, 9)
        self._booking(departure=booked, pax=1)
        self._at(self.week_from, 14)

        self.assertEqual(self._grid(show="booked")["stats"]["departures"], 2)

    def test_departures_outside_the_week_are_left_out(self):
        self._at(self.week_from, 9)
        self._at(self.week_to + timedelta(days=1), 9)

        grid = self._grid()

        self.assertEqual(grid["stats"]["departures"], 1)

    def test_an_empty_week_still_returns_seven_days(self):
        grid = self._grid()

        self.assertEqual(len(grid["days"]), 7)
        self.assertEqual(grid["rows"], [])
        self.assertEqual(grid["stats"]["departures"], 0)

    def test_today_is_marked_so_the_column_can_be_highlighted(self):
        today = fields.Date.context_today(self.env["tour.tour"])

        grid = self._grid(date_from=today, date_to=today + timedelta(days=6))

        self.assertTrue(grid["days"][0]["is_today"])
        self.assertFalse(grid["days"][1]["is_today"])
