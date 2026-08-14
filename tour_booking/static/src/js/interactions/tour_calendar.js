import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { formatCurrency } from "@web/core/currency";
import { _t } from "@web/core/l10n/translation";

/**
 * The booking widget: a month of dates, a start time, a party size.
 *
 * One month at a time, by design: a guest choosing a day out does not page
 * through a year, and the server only ever sends the month being looked at.
 *
 * What is bookable is decided entirely by the server. This renders the days it
 * is handed and nothing else — it has no idea what a cut-off is, and so cannot
 * offer a departure the booking would then refuse.
 *
 * An Interaction rather than the old publicWidget: this markup is now a website
 * snippet as well as a page, and an Interaction is what the builder starts when
 * a block is dropped and restarts when the editor reloads.
 */
export class TourCalendar extends Interaction {
    static selector = ".o_tour_widget";

    // Bound to the four containers rather than to the cells inside them. The
    // cells are rewritten on every month change; the containers are not, so
    // these listeners survive a re-render and nothing has to be re-bound.
    dynamicContent = {
        ".o_tour_prev": { "t-on-click": () => this.shiftMonth(-1) },
        ".o_tour_next": { "t-on-click": () => this.shiftMonth(1) },
        ".o_tour_grid": {
            "t-on-click": (ev) => this.onGridClick(ev),
            "t-on-keydown": (ev) => this.onGridKey(ev),
        },
        ".o_tour_time_options": { "t-on-click": (ev) => this.onTimeClick(ev) },
        ".o_tour_pax": { "t-on-change": (ev) => this.onChangePax(ev) },
    };

    setup() {
        this.tourId = parseInt(this.el.dataset.tourId, 10);
        this.month = this.el.dataset.month;
        this.selected = null;
        this.days = {};
        this.hasSpecificTime = true;
        this.price = parseFloat(this.el.dataset.price) || 0;
        this.currencyId = parseInt(this.el.dataset.currency, 10);
        // Only set when the operator's provider settles in another currency.
        this.settlementCurrencyId = parseInt(this.el.dataset.settlementCurrency, 10);
        this.settlementRate = parseFloat(this.el.dataset.settlementRate) || 0;
    }

    async willStart() {
        await this.load();
    }

    start() {
        this.restoreChoice();
    }

    // --- Data ---------------------------------------------------------------

    async load() {
        const result = await this.waitFor(
            rpc(`/tour/${this.tourId}/availability`, { month: this.month })
        );
        this.days = result.days || {};
        this.hasSpecificTime = result.has_specific_time;
        this.renderMonth();
    }

    monthDate() {
        const [year, month] = this.month.split("-").map(Number);
        return new Date(year, month - 1, 1);
    }

    async shiftMonth(delta) {
        const date = this.monthDate();
        date.setMonth(date.getMonth() + delta);
        this.month = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
        this.clearSelection();
        await this.load();
    }

    // --- Rendering ----------------------------------------------------------

    renderMonth() {
        const first = this.monthDate();
        this.el.querySelector(".o_tour_month_label").textContent =
            first.toLocaleDateString(undefined, { month: "long", year: "numeric" });

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
                // A day you can book is a control, and a control has to be
                // reachable by keyboard. The ones you cannot book are not, or
                // tabbing through a month would mean thirty stops at nothing.
                cell.tabIndex = 0;
                cell.setAttribute("role", "button");
            } else {
                cell.classList.add("unavailable");
            }
            grid.appendChild(cell);
        }
    }

    clearSelection() {
        this.selected = null;
        for (const cell of this.el.querySelectorAll(".o_tour_day.selected")) {
            cell.classList.remove("selected");
        }
        this.el.querySelector(".o_tour_times").classList.add("d-none");
        this.el.querySelector(".o_tour_departure_input").value = "";
        this.el.querySelector(".o_tour_book_button").disabled = true;
        this.el.querySelector(".o_tour_seats_left").textContent = "";
        this.el.querySelector(".o_tour_hint").textContent = "Pick a date to continue.";
        this.el.querySelector(".o_tour_total").classList.add("d-none");
    }

    // --- Picking ------------------------------------------------------------

    onGridClick(ev) {
        const cell = ev.target.closest(".o_tour_day.available");
        if (cell) {
            this.pickDay(cell);
        }
    }

    /**
     * The day cells are `div`s carrying `role="button"`, so nothing gives them
     * Enter and Space for free. Space is prevented as well as handled: left
     * alone it scrolls the page away from the card being filled in.
     */
    onGridKey(ev) {
        if (ev.key !== "Enter" && ev.key !== " ") {
            return;
        }
        const cell = ev.target.closest(".o_tour_day.available");
        if (cell) {
            ev.preventDefault();
            this.pickDay(cell);
        }
    }

    pickDay(cell) {
        this.clearSelection();
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
            this.select(departures[0]);
        }
    }

    onTimeClick(ev) {
        const button = ev.target.closest(".o_tour_time_option");
        if (!button) {
            return;
        }
        for (const other of this.el.querySelectorAll(".o_tour_time_option")) {
            other.classList.remove("active");
        }
        button.classList.add("active");
        this.select({
            id: parseInt(button.dataset.departureId, 10),
            seats_available: parseInt(button.dataset.seats, 10),
            min_pax: parseInt(button.dataset.minPax, 10),
            max_pax: parseInt(button.dataset.maxPax, 10),
        });
    }

    select(departure) {
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
        this.renderTotal();
    }

    onChangePax(ev) {
        if (!this.selected) {
            return;
        }
        const input = ev.target;
        const max = Math.min(this.selected.max_pax, this.selected.seats_available);
        let value = parseInt(input.value, 10) || this.selected.min_pax;
        input.value = Math.max(this.selected.min_pax, Math.min(value, max));
        this.renderTotal();
    }

    /**
     * What the party will pay for the seats.
     *
     * Deliberately the seats only. Extras and taxes are chosen at the next
     * step and priced by the server, and a "total" here that quietly excluded
     * them without saying so would be the number a guest remembers and then
     * argues about.
     */
    renderTotal() {
        const total = this.el.querySelector(".o_tour_total");
        if (!this.selected || !this.price) {
            total.classList.add("d-none");
            return;
        }
        const pax = parseInt(this.el.querySelector(".o_tour_pax").value, 10) || 1;
        this.el.querySelector(".o_tour_total_label").textContent = _t(
            "%(pax)s x %(price)s",
            { pax, price: formatCurrency(this.price, this.currencyId) }
        );
        this.el.querySelector(".o_tour_total_value").textContent =
            formatCurrency(this.price * pax, this.currencyId);
        this.renderSettlement(this.price * pax);
        total.classList.remove("d-none");
    }

    /**
     * "≈ €135 at today's rate", when the card will be charged in another
     * currency than the one the tour is priced in.
     *
     * Hedged on purpose. The rate is fixed by the server when the booking is
     * created, not now, so this is today's rate and may have moved by the time
     * the guest reaches checkout — where the figure stops being approximate and
     * says so.
     */
    renderSettlement(amount) {
        const line = this.el.querySelector(".o_tour_total_settlement");
        if (!line || !this.settlementRate || !this.settlementCurrencyId) {
            return;
        }
        line.textContent = _t("≈ %(amount)s at today's rate", {
            amount: formatCurrency(amount * this.settlementRate, this.settlementCurrencyId),
        });
    }

    // --- Arriving with a choice already made --------------------------------

    /**
     * A guest who pressed Book now in an embedded frame lands here, on the
     * operator's own domain, with their date and party size in the URL. Putting
     * them back on an empty calendar would make them choose twice.
     *
     * The server has already set the month to the departure's own, so it is in
     * the data that has just loaded.
     */
    restoreChoice() {
        const wanted = parseInt(this.el.dataset.preselectDeparture, 10);
        if (!wanted) {
            return;
        }
        for (const [date, departures] of Object.entries(this.days)) {
            const departure = departures.find((d) => d.id === wanted);
            if (!departure) {
                continue;
            }
            const cell = this.el.querySelector(`.o_tour_day[data-date="${date}"]`);
            if (cell) {
                this.pickDay(cell);
            }
            this.select(departure);
            const pax = parseInt(this.el.dataset.preselectPax, 10);
            if (pax) {
                const input = this.el.querySelector(".o_tour_pax");
                input.value = pax;
                input.dispatchEvent(new Event("change"));
            }
            if (this.el.dataset.autobook) {
                // Submitted from here rather than from the frame it was chosen
                // in: this page is first-party, so the CSRF token in the form
                // is one the server will actually accept.
                this.el.querySelector(".o_tour_book_form").submit();
            }
            return;
        }
    }
}

registry.category("public.interactions").add("tour_booking.tour_calendar", TourCalendar);
