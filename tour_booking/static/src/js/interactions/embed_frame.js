import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";

/**
 * The half of the embed that runs inside the iframe.
 *
 * Two jobs, both of which exist because a cross-origin iframe is a sealed box:
 *
 * 1. It reports its own height. An iframe cannot size itself to its content
 *    from the outside, so the page measures itself and the host applies it.
 *
 * 2. It refuses to submit the booking. Odoo's session cookie is `SameSite=Lax`
 *    by default and is simply not sent inside a third-party frame, so
 *    `request.csrf_token()` in this document was minted against a session that
 *    will not exist on the next request — the POST would be rejected, and in
 *    Safari and Firefox there is no cookie at all. Instead the choice is handed
 *    to the host page as a first-party URL, and the guest finishes on the
 *    operator's own domain where all of this works.
 */
export class EmbedFrame extends Interaction {
    // `website.layout` puts `pageName` on `#wrapwrap`, not on the body, which
    // is why the marker class is looked for there.
    static selector = "#wrapwrap.o_tour_embed";

    dynamicContent = {
        ".o_tour_book_form": { "t-on-submit.prevent": (ev) => this.onBook(ev) },
    };

    setup() {
        this.lastHeight = 0;
    }

    start() {
        this.postHeight();
        // The height changes whenever a month is rendered or the start-time
        // options appear, neither of which is an event anybody emits.
        this.observer = new ResizeObserver(() => this.postHeight());
        this.observer.observe(this.el);
        this.registerCleanup(() => this.observer.disconnect());
    }

    postHeight() {
        // The document, not the observed element: margins and anything the
        // theme puts outside the wrapper still take up room in the frame, and a
        // height that ignores them produces a widget with its own scrollbar.
        const height = Math.ceil(document.documentElement.scrollHeight);
        if (height && height !== this.lastHeight) {
            this.lastHeight = height;
            window.parent.postMessage({ tour_booking: "resize", height }, "*");
        }
    }

    onBook(ev) {
        const form = ev.currentTarget;
        const widget = form.closest(".o_tour_widget");
        const departure = form.querySelector(".o_tour_departure_input").value;
        if (!departure) {
            return;
        }
        const url = new URL(widget.dataset.tourUrl, window.location.origin);
        url.searchParams.set("departure_id", departure);
        url.searchParams.set("pax", form.querySelector(".o_tour_pax").value || "1");
        url.searchParams.set("autobook", "1");
        // `*` as the target origin: this frame does not know, and has no way to
        // learn, which site embedded it. The message carries a public URL and
        // nothing else, so there is nothing here to leak.
        window.parent.postMessage(
            { tour_booking: "navigate", url: url.href }, "*"
        );
    }
}

registry.category("public.interactions").add("tour_booking.embed_frame", EmbedFrame);
