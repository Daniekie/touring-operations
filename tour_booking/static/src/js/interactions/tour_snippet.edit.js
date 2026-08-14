import { registry } from "@web/core/registry";
import { TourCalendar } from "./tour_calendar";
import { TourSnippet } from "./tour_snippet";

/**
 * The same block, alive inside the website editor.
 *
 * An interaction registered only in `public.interactions` does not run while
 * editing, so these blocks drew nothing until the page was saved — an operator
 * dropped one, got a white band, and had no way to tell that from a block that
 * does not work. It does not help that it then works perfectly on the live
 * page.
 *
 * Fetching for real rather than showing a mock-up: the operator is choosing
 * which experience the block shows, and needs to see the one they chose. The
 * fetched markup is inserted through `insert()`, which removes it again when
 * the interaction is destroyed — and the builder stops interactions before it
 * serialises the page, so none of it is saved into the arch. That is the whole
 * reason these blocks are shells.
 */
registry.category("public.interactions.edit").add("tour_booking.snippet", {
    Interaction: TourSnippet,
});

/**
 * And the calendar inside it, for the same reason.
 *
 * Without this the block draws its card — price, party size, Book now — around
 * an empty rectangle where the month belongs, which reads as broken rather
 * than as unfinished.
 */
const TourCalendarEdit = (I) =>
    class extends I {
        /** The dates are there to be looked at while laying out a page, not
         *  clicked. Submitting a booking from the editor would be worse. */
        restoreChoice() {}
    };

registry.category("public.interactions.edit").add("tour_booking.tour_calendar", {
    Interaction: TourCalendar,
    mixin: TourCalendarEdit,
});
