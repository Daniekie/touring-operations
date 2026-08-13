/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/**
 * The Booking Calendar: start times down the side, days across the top.
 *
 * Odoo's stock calendar lays events along a time axis, which answers "what is
 * happening now" — the wrong question for a tour operator, who is reading a
 * week to see which trips are filling up. So the grid is its own component.
 *
 * It computes nothing. The server returns rows, columns, counts and colours
 * already assembled, and this draws them: a rule about what counts as sold out
 * or in need of attention should never have two implementations.
 */
export class BookingCalendar extends Component {
    static template = "tour_booking.BookingCalendar";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            anchor: this.startOfWeek(new Date()),
            span: "week",
            mode: "time",
            show: "all",
            grid: { stats: {}, days: [], rows: [] },
            loading: true,
        });

        onWillStart(() => this.load());
    }

    // --- The window ---------------------------------------------------------

    /** Monday of the week containing `date`. */
    startOfWeek(date) {
        const start = new Date(date);
        start.setHours(0, 0, 0, 0);
        // getDay() is Sunday-based; the schedule is read Monday-first.
        start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
        return start;
    }

    get rangeEnd() {
        const end = new Date(this.state.anchor);
        end.setDate(end.getDate() + (this.state.span === "week" ? 6 : 0));
        return end;
    }

    /** ISO date, built from local parts — `toISOString` would shift the day
     *  for anyone east or west of UTC, which is most people. */
    toIso(date) {
        const month = String(date.getMonth() + 1).padStart(2, "0");
        const day = String(date.getDate()).padStart(2, "0");
        return `${date.getFullYear()}-${month}-${day}`;
    }

    get rangeLabel() {
        const start = this.state.anchor;
        if (this.state.span === "day") {
            return start.toLocaleDateString(undefined, {
                weekday: "long", day: "numeric", month: "long", year: "numeric",
            });
        }
        const week = this.weekNumber(start);
        const month = start.toLocaleDateString(undefined, { month: "long", year: "numeric" });
        return _t("Week %(week)s - %(month)s", { week, month });
    }

    weekNumber(date) {
        const target = new Date(date.getTime());
        target.setHours(0, 0, 0, 0);
        // ISO-8601: week 1 is the one containing the first Thursday.
        target.setDate(target.getDate() + 3 - ((target.getDay() + 6) % 7));
        const firstThursday = new Date(target.getFullYear(), 0, 4);
        firstThursday.setDate(
            firstThursday.getDate() + 3 - ((firstThursday.getDay() + 6) % 7)
        );
        return 1 + Math.round((target - firstThursday) / (7 * 24 * 3600 * 1000));
    }

    // --- Data ---------------------------------------------------------------

    async load() {
        this.state.loading = true;
        try {
            this.state.grid = await this.orm.call(
                "tour.departure",
                "get_calendar_grid",
                [this.toIso(this.state.anchor), this.toIso(this.rangeEnd)],
                { mode: this.state.mode, show: this.state.show },
            );
        } finally {
            this.state.loading = false;
        }
    }

    shift(direction) {
        const anchor = new Date(this.state.anchor);
        anchor.setDate(anchor.getDate() + direction * (this.state.span === "week" ? 7 : 1));
        this.state.anchor = anchor;
        this.load();
    }

    today() {
        this.state.anchor =
            this.state.span === "week" ? this.startOfWeek(new Date()) : new Date();
        this.load();
    }

    setSpan(span) {
        this.state.span = span;
        this.state.anchor =
            span === "week" ? this.startOfWeek(this.state.anchor) : this.state.anchor;
        this.load();
    }

    setMode(mode) {
        this.state.mode = mode;
        this.load();
    }

    setShow(show) {
        this.state.show = show;
        this.load();
    }

    // --- Reading a cell -----------------------------------------------------

    cells(row, day) {
        return row.cells[day.date] || [];
    }

    /** How full a trip is, as a percentage, for the bar under the card. */
    fillPercent(cell) {
        if (!cell.capacity) {
            return 0;
        }
        return Math.min(100, Math.round((cell.seats_sold / cell.capacity) * 100));
    }

    cellClass(cell) {
        const classes = [`o_tour_cell`, `o_tour_color_${cell.color}`];
        if (cell.state === "cancelled") {
            classes.push("o_tour_cell_cancelled");
        } else if (cell.seats_sold >= cell.capacity) {
            classes.push("o_tour_cell_full");
        } else if (cell.seats_sold > 0) {
            classes.push("o_tour_cell_booked");
        }
        return classes.join(" ");
    }

    openDeparture(cell) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "tour.departure",
            res_id: cell.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openList() {
        this.action.doAction("tour_booking.tour_departure_action");
    }
}

registry.category("actions").add("tour_booking.booking_calendar", BookingCalendar);
