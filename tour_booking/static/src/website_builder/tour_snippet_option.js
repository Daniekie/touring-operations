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

/** The booking box on its own: which experience it sells. */
export class TourBookOption extends TourOptionBase {
    static template = "tour_booking.TourPickExperienceOption";
    static selector = ".s_tour_book";
}
