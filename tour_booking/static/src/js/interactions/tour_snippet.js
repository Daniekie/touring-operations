import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

/**
 * Fills a booking block with its content.
 *
 * The blocks are shells on purpose. The website editor saves the rendered DOM
 * of whatever the operator dropped, so a block that rendered its experiences
 * server-side would have them frozen into the page at drop time — a new
 * experience would never appear, and last season's prices would sit there
 * until somebody noticed. Fetching on every load is what keeps the block and
 * the catalogue the same thing.
 *
 * `insert` rather than `innerHTML`: it starts the interactions on what it puts
 * in, which is how the calendar inside a booking box comes alive.
 */
export class TourSnippet extends Interaction {
    static selector = ".s_tour_dynamic";

    async willStart() {
        const data = this.el.dataset;
        this.html = "";
        const result = await this.waitFor(
            rpc("/tour/snippet", {
                widget: data.tourWidget,
                tour_id: data.tourId,
                columns: data.tourColumns,
                limit: data.tourLimit,
            })
        );
        this.html = result.html || "";
    }

    start() {
        const target = this.el.querySelector(".o_tour_snippet_content");
        if (!target) {
            return;
        }
        if (!this.html) {
            // A booking block with no experience chosen yet. The operator is
            // looking at this in the editor and needs to be told what to do,
            // not left with an empty band of page.
            const hint = document.createElement("div");
            hint.className = "o_tour_snippet_empty";
            hint.textContent = _t(
                "Pick an experience for this block in the panel on the right."
            );
            this.insert(hint, target);
            return;
        }
        const holder = document.createElement("div");
        holder.innerHTML = this.html;
        for (const child of [...holder.children]) {
            this.insert(child, target);
        }
    }
}

registry.category("public.interactions").add("tour_booking.snippet", TourSnippet);
