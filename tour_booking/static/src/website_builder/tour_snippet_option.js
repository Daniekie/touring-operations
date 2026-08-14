import { BaseOptionComponent } from "@html_builder/core/utils";
import { onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * The panel on the right for a booking block.
 *
 * The experience list is fetched rather than hardcoded for the obvious reason,
 * and only published ones are offered: an unpublished experience renders as
 * nothing on the live page, so offering it here would be offering a way to
 * build a page that silently shows an empty band.
 */
class TourOptionBase extends BaseOptionComponent {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.tours = useState({ records: [] });
        onWillStart(async () => {
            this.tours.records = await this.orm.searchRead(
                "tour.tour",
                [["is_published", "=", true]],
                ["id", "name"],
                { order: "sequence, name" }
            );
        });
    }
}

/** The catalogue: how many across, and how many at all. */
export class TourExperiencesOption extends TourOptionBase {
    static template = "tour_booking.TourExperiencesOption";
    static selector = ".s_tour_experiences";
}

/** One experience, whole. */
export class TourExperienceOption extends TourOptionBase {
    static template = "tour_booking.TourExperienceOption";
    static selector = ".s_tour_experience";
}

/** The booking box on its own. */
export class TourBookOption extends TourOptionBase {
    static template = "tour_booking.TourExperienceOption";
    static selector = ".s_tour_book";
}

/** The button, which opens the catalogue. */
export class TourBookButtonOption extends TourOptionBase {
    static template = "tour_booking.TourBookButtonOption";
    static selector = ".s_tour_book_button";
}
