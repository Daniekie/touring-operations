import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

/**
 * The checkout: keep the summary honest while the guest is still choosing.
 *
 * Extras used to be priced only when Save details was pressed, so adding a
 * wetsuit changed nothing on the page — the guest either believed the stale
 * total or pressed a button they had no reason to press. Now every change goes
 * to the server, which saves it and hands back the re-rendered summary.
 *
 * Deliberately no arithmetic here. The browser sends quantities and nothing
 * else; what an extra costs, how it is taxed and what the total comes to are
 * the server's answers, and re-implementing them in JavaScript is how the card
 * ends up disagreeing with the charge.
 */
export class TourCheckout extends Interaction {
    static selector = ".o_tour_checkout";

    // Bound to the container, not to each box: there is one listener whatever
    // the tour sells, and it survives the summary being replaced.
    dynamicContent = {
        ".o_tour_extras": {
            "t-on-input": (ev) => this.onExtraInput(ev),
            "t-on-change": (ev) => this.onExtraInput(ev),
        },
    };

    setup() {
        this.bookingId = parseInt(this.el.dataset.bookingId, 10);
        this.accessToken = this.el.dataset.accessToken;
        // Long enough that typing "12" is one request rather than two, short
        // enough that the total has settled before the eye gets back to it.
        this.reprice = this.debounced(() => this.repriceNow(), 400);
    }

    onExtraInput(ev) {
        const input = ev.target.closest(".o_tour_extra_qty");
        if (!input) {
            return;
        }
        // A negative quantity is a subtraction from the bill. The server floors
        // it too; this is so the box never shows one.
        if (parseInt(input.value, 10) < 0) {
            input.value = 0;
        }
        this.reprice();
    }

    async repriceNow() {
        const quantities = {};
        for (const input of this.el.querySelectorAll(".o_tour_extra_qty")) {
            quantities[input.name] = parseInt(input.value, 10) || 0;
        }
        const result = await this.waitFor(rpc(
            `/tour/booking/${this.bookingId}/extras`,
            Object.assign({ access_token: this.accessToken }, quantities),
        ));
        // Server-rendered markup from our own template, swapped in whole: the
        // extras lines appear and disappear as they are chosen, so patching
        // individual cells would mean rebuilding the table row by row.
        this.el.querySelector(".o_tour_summary").innerHTML = result.html;
    }
}

registry.category("public.interactions").add("tour_booking.tour_checkout", TourCheckout);
