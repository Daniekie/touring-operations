import { Interaction } from "@web/public/interaction";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/**
 * The photo mosaic, and the lightbox behind it.
 *
 * Every photo is already in the page — the ones past the fourth are simply
 * hidden — so paging through them costs nothing and works with the network
 * off. That is the whole reason the mosaic renders the overflow rather than
 * fetching it when the lightbox opens.
 *
 * Built here rather than reusing the website's own image-gallery snippet:
 * that one belongs to a snippet an operator drags in and configures, and this
 * is a fixed part of a tour page.
 */
export class TourGallery extends Interaction {
    static selector = ".o_tour_photos";

    dynamicContent = {
        _root: {
            // Marks the mosaic as live. The tiles exist in the HTML long
            // before this is listening, so without something observable a
            // test — or a fast visitor — clicks a photo into the void.
            "t-att-class": () => ({ o_tour_photos_ready: true }),
            "t-on-click": (ev) => this.onClick(ev),
        },
        _document: { "t-on-keydown": (ev) => this.onKey(ev) },
    };

    setup() {
        this.photos = [...this.el.querySelectorAll(".o_tour_photo img")];
        this.index = 0;
        this.overlay = null;
    }

    onClick(ev) {
        if (ev.target.closest(".o_tour_photos_all")) {
            return this.open(0);
        }
        const figure = ev.target.closest(".o_tour_photo");
        if (figure) {
            this.open(parseInt(figure.dataset.index, 10) || 0);
        }
    }

    // --- The lightbox -------------------------------------------------------

    open(index) {
        if (!this.photos.length) {
            return;
        }
        if (!this.overlay) {
            this.build();
        }
        this.show(index);
        this.overlay.classList.remove("d-none");
        // The page behind must not scroll under the overlay; a lightbox that
        // moves when you flick at it feels broken.
        this.el.ownerDocument.body.classList.add("o_tour_lightbox_open");
    }

    close() {
        if (this.overlay) {
            this.overlay.classList.add("d-none");
        }
        this.el.ownerDocument.body.classList.remove("o_tour_lightbox_open");
    }

    get isOpen() {
        return !!this.overlay && !this.overlay.classList.contains("d-none");
    }

    build() {
        const overlay = document.createElement("div");
        overlay.className = "o_tour_lightbox d-none";
        overlay.innerHTML = `
            <button type="button" class="o_tour_lightbox_close" aria-label="${_t("Close")}">&times;</button>
            <button type="button" class="o_tour_lightbox_prev" aria-label="${_t("Previous")}">&#10094;</button>
            <figure class="o_tour_lightbox_stage"><img alt=""/></figure>
            <button type="button" class="o_tour_lightbox_next" aria-label="${_t("Next")}">&#10095;</button>
            <div class="o_tour_lightbox_count"></div>
        `;
        overlay.addEventListener("click", (ev) => {
            if (ev.target.closest(".o_tour_lightbox_next")) {
                this.show(this.index + 1);
            } else if (ev.target.closest(".o_tour_lightbox_prev")) {
                this.show(this.index - 1);
            } else if (!ev.target.closest(".o_tour_lightbox_stage")) {
                // The backdrop closes it; the photograph itself does not, or
                // every attempt to look closely shuts the thing.
                this.close();
            }
        });
        // `insert` so it is torn down with the interaction — the editor starts
        // and stops these, and a lightbox left behind would stack up.
        this.insert(overlay, this.el.ownerDocument.body);
        this.overlay = overlay;
    }

    show(index) {
        // Wraps in both directions: at the last photo, Next returns to the
        // first rather than doing nothing and looking broken.
        const count = this.photos.length;
        this.index = (index + count) % count;
        const photo = this.photos[this.index];
        const image = this.overlay.querySelector(".o_tour_lightbox_stage img");
        image.src = photo.src;
        image.alt = photo.alt || "";
        this.overlay.querySelector(".o_tour_lightbox_count").textContent =
            `${this.index + 1} / ${count}`;
        // One photo is not a slideshow.
        for (const selector of [".o_tour_lightbox_prev", ".o_tour_lightbox_next"]) {
            this.overlay.querySelector(selector).classList.toggle("d-none", count < 2);
        }
    }

    onKey(ev) {
        if (!this.isOpen) {
            return;
        }
        if (ev.key === "Escape") {
            this.close();
        } else if (ev.key === "ArrowRight") {
            this.show(this.index + 1);
        } else if (ev.key === "ArrowLeft") {
            this.show(this.index - 1);
        }
    }
}

registry.category("public.interactions").add("tour_booking.tour_gallery", TourGallery);
