/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { rpc } from "@web/core/network/rpc";

/**
 * The booking widget on a tour page.
 *
 * One month at a time, by design: a guest choosing a day out does not page
 * through a year, and the server only ever sends the month being looked at.
 *
 * What is bookable is decided entirely by the server. This widget renders the
 * days it is handed and nothing else — it has no idea what a cut-off is, and
 * cannot accidentally offer a departure the booking would then refuse.
 */
publicWidget.registry.TourBookingWidget = publicWidget.Widget.extend({
    selector: ".o_tour_widget",
    events: {
        "click .o_tour_prev": "_onPrevMonth",
        "click .o_tour_next": "_onNextMonth",
        "click .o_tour_day.available": "_onPickDay",
        "click .o_tour_time_option": "_onPickTime",
        "change .o_tour_pax": "_onChangePax",
    },

    async start() {
        this.tourId = parseInt(this.el.dataset.tourId, 10);
        this.month = this.el.dataset.month;
        this.selected = null;
        await this._load();
        return this._super(...arguments);
    },

    async _load() {
        const result = await rpc(`/tour/${this.tourId}/availability`, {
            month: this.month,
        });
        this.days = result.days || {};
        this.hasSpecificTime = result.has_specific_time;
        this._renderMonth();
    },

    _monthDate() {
        const [year, month] = this.month.split("-").map(Number);
        return new Date(year, month - 1, 1);
    },

    _shiftMonth(delta) {
        const date = this._monthDate();
        date.setMonth(date.getMonth() + delta);
        this.month = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
        this._clearSelection();
        return this._load();
    },

    _renderMonth() {
        const first = this._monthDate();
        const label = first.toLocaleDateString(undefined, {
            month: "long",
            year: "numeric",
        });
        this.el.querySelector(".o_tour_month_label").textContent = label;

        const daysInMonth = new Date(
            first.getFullYear(), first.getMonth() + 1, 0
        ).getDate();
        // Monday-first, which is what the rest of the schedule is written in.
        const offset = (first.getDay() + 6) % 7;

        const grid = this.el.querySelector(".o_tour_grid");
        grid.innerHTML = "";

        for (const name of ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]) {
            const head = document.createElement("div");
            head.className = "o_tour_dow";
            head.textContent = name;
            grid.appendChild(head);
        }
        for (let i = 0; i < offset; i++) {
            grid.appendChild(document.createElement("div"));
        }
        for (let day = 1; day <= daysInMonth; day++) {
            const iso = `${this.month}-${String(day).padStart(2, "0")}`;
            const cell = document.createElement("div");
            cell.className = "o_tour_day";
            cell.textContent = day;
            if (this.days[iso]) {
                cell.classList.add("available");
                cell.dataset.date = iso;
            } else {
                cell.classList.add("unavailable");
            }
            grid.appendChild(cell);
        }
    },

    _clearSelection() {
        this.selected = null;
        this.el.querySelectorAll(".o_tour_day.selected").forEach((cell) => {
            cell.classList.remove("selected");
        });
        this.el.querySelector(".o_tour_times").classList.add("d-none");
        this.el.querySelector(".o_tour_departure_input").value = "";
        this.el.querySelector(".o_tour_book_button").disabled = true;
        this.el.querySelector(".o_tour_seats_left").textContent = "";
        this.el.querySelector(".o_tour_hint").textContent = "Pick a date to continue.";
    },

    _onPrevMonth() {
        this._shiftMonth(-1);
    },

    _onNextMonth() {
        this._shiftMonth(1);
    },

    _onPickDay(event) {
        const cell = event.currentTarget;
        this._clearSelection();
        cell.classList.add("selected");

        const departures = this.days[cell.dataset.date] || [];
        const container = this.el.querySelector(".o_tour_times");
        const options = this.el.querySelector(".o_tour_time_options");
        options.innerHTML = "";

        // Times are only worth showing when there is a choice to make. A date
        // with one departure is already unambiguous.
        if (this.hasSpecificTime && departures.length > 1) {
            container.classList.remove("d-none");
            for (const departure of departures) {
                const button = document.createElement("button");
                button.type = "button";
                button.className = "btn btn-outline-primary o_tour_time_option";
                button.textContent = departure.time;
                button.dataset.departureId = departure.id;
                button.dataset.seats = departure.seats_available;
                button.dataset.minPax = departure.min_pax;
                button.dataset.maxPax = departure.max_pax;
                options.appendChild(button);
            }
            this.el.querySelector(".o_tour_hint").textContent =
                "Pick a start time to continue.";
        } else if (departures.length) {
            this._select(departures[0]);
        }
    },

    _onPickTime(event) {
        const button = event.currentTarget;
        this.el.querySelectorAll(".o_tour_time_option").forEach((other) => {
            other.classList.remove("active");
        });
        button.classList.add("active");
        this._select({
            id: parseInt(button.dataset.departureId, 10),
            seats_available: parseInt(button.dataset.seats, 10),
            min_pax: parseInt(button.dataset.minPax, 10),
            max_pax: parseInt(button.dataset.maxPax, 10),
        });
    },

    _select(departure) {
        this.selected = departure;
        this.el.querySelector(".o_tour_departure_input").value = departure.id;
        this.el.querySelector(".o_tour_book_button").disabled = false;
        this.el.querySelector(".o_tour_hint").textContent = "";

        // The party size is bounded by both the departure's own limits and by
        // what is left. The server enforces all three again; this is only so a
        // guest is not invited to fill in something that will be refused.
        const pax = this.el.querySelector(".o_tour_pax");
        const max = Math.min(departure.max_pax, departure.seats_available);
        pax.min = departure.min_pax;
        pax.max = max;
        if (parseInt(pax.value, 10) < departure.min_pax) {
            pax.value = departure.min_pax;
        }
        if (parseInt(pax.value, 10) > max) {
            pax.value = max;
        }
        this.el.querySelector(".o_tour_seats_left").textContent =
            `${departure.seats_available} seat(s) left`;
    },

    _onChangePax(event) {
        if (!this.selected) {
            return;
        }
        const input = event.currentTarget;
        const max = Math.min(this.selected.max_pax, this.selected.seats_available);
        let value = parseInt(input.value, 10) || this.selected.min_pax;
        value = Math.max(this.selected.min_pax, Math.min(value, max));
        input.value = value;
    },
});

export default publicWidget.registry.TourBookingWidget;
