/**
 * The script an operator pastes into their own website.
 *
 *   <script src="https://tours.example.com/tour/embed.js" async></script>
 *   <div data-tour-widget="experiences"></div>
 *   <div data-tour-widget="experience" data-tour-id="3"></div>
 *   <div data-tour-widget="book" data-tour-id="3"></div>
 *   <div data-tour-widget="button" data-tour-label="Book now"></div>
 *
 * This runs on somebody else's page, so it is deliberately plain: no imports,
 * no build step, no framework, no globals beyond one guard. It must not care
 * what else is on the page, and nothing on the page should have to care about
 * it.
 *
 * Two messages come back from the frame:
 *
 *   resize   — an iframe cannot size itself across origins, so the page inside
 *              measures itself and the host applies it. Without this every
 *              widget is a fixed box with its own scrollbar.
 *   navigate — Book now. The frame refuses to submit a booking itself, because
 *              a cross-origin frame gets no session cookie and so no usable
 *              CSRF token. It hands up a first-party URL and this opens it.
 */
(function () {
    "use strict";

    if (window.__tourBookingEmbedLoaded) {
        return;
    }
    window.__tourBookingEmbedLoaded = true;

    // Where this script was served from is where the widgets live. Reading it
    // off the script tag means the operator pastes one URL, not two, and a test
    // or staging instance embeds itself rather than production.
    var origin = (function () {
        var script = document.currentScript;
        if (!script) {
            var all = document.getElementsByTagName("script");
            for (var i = all.length - 1; i >= 0; i--) {
                if (all[i].src && all[i].src.indexOf("/tour/embed.js") !== -1) {
                    script = all[i];
                    break;
                }
            }
        }
        try {
            return new URL(script.src).origin;
        } catch (error) {
            return "";
        }
    })();

    var MIN_HEIGHT = 400;

    function frameUrl(host) {
        var widget = host.getAttribute("data-tour-widget");
        var tourId = host.getAttribute("data-tour-id");
        var columns = host.getAttribute("data-tour-columns");
        // A button opens the catalogue, so it falls through to the same URL.
        if ((widget === "experience" || widget === "book") && tourId) {
            return origin + "/tour/embed/" + widget + "/" + encodeURIComponent(tourId);
        }
        return (
            origin + "/tour/embed/experiences" +
            (columns ? "?columns=" + encodeURIComponent(columns) : "")
        );
    }

    function buildFrame(src, minHeight) {
        var frame = document.createElement("iframe");
        frame.src = src;
        frame.className = "tour-booking-frame";
        frame.setAttribute("title", "Booking");
        frame.setAttribute("loading", "lazy");
        frame.setAttribute("allow", "payment");
        frame.style.width = "100%";
        frame.style.border = "0";
        frame.style.display = "block";
        frame.style.height = (minHeight || MIN_HEIGHT) + "px";
        return frame;
    }

    // --- The button, which is the only widget that is not just a frame -------

    function buildButton(host) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "tour-booking-button";
        button.textContent = host.getAttribute("data-tour-label") || "Book now";
        button.addEventListener("click", function () {
            openOverlay(frameUrl(host));
        });
        host.appendChild(button);
    }

    function openOverlay(src) {
        var overlay = document.createElement("div");
        overlay.className = "tour-booking-overlay";
        setStyles(overlay, {
            position: "fixed",
            inset: "0",
            zIndex: "2147483000",
            background: "rgba(0, 0, 0, .6)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            padding: "3vh 1rem",
            overflow: "auto",
        });

        var panel = document.createElement("div");
        setStyles(panel, {
            position: "relative",
            width: "100%",
            maxWidth: "1100px",
            background: "#fff",
            borderRadius: ".5rem",
            overflow: "hidden",
        });

        var close = document.createElement("button");
        close.type = "button";
        close.setAttribute("aria-label", "Close");
        close.innerHTML = "&times;";
        setStyles(close, {
            position: "absolute",
            top: ".25rem",
            right: ".5rem",
            zIndex: "1",
            border: "0",
            background: "transparent",
            fontSize: "2rem",
            lineHeight: "1",
            cursor: "pointer",
        });

        function dismiss() {
            overlay.remove();
            document.removeEventListener("keydown", onKey);
        }
        function onKey(event) {
            if (event.key === "Escape") {
                dismiss();
            }
        }
        close.addEventListener("click", dismiss);
        overlay.addEventListener("click", function (event) {
            // Only the backdrop closes it. A click that lands on the panel is
            // somebody using the widget.
            if (event.target === overlay) {
                dismiss();
            }
        });
        document.addEventListener("keydown", onKey);

        panel.appendChild(close);
        panel.appendChild(buildFrame(src, Math.round(window.innerHeight * 0.8)));
        overlay.appendChild(panel);
        document.body.appendChild(overlay);
    }

    function setStyles(el, styles) {
        for (var key in styles) {
            if (Object.prototype.hasOwnProperty.call(styles, key)) {
                el.style[key] = styles[key];
            }
        }
    }

    // --- Wiring -------------------------------------------------------------

    function mount() {
        var hosts = document.querySelectorAll("[data-tour-widget]");
        for (var i = 0; i < hosts.length; i++) {
            var host = hosts[i];
            if (host.getAttribute("data-tour-mounted")) {
                continue;
            }
            host.setAttribute("data-tour-mounted", "1");
            if (host.getAttribute("data-tour-widget") === "button") {
                buildButton(host);
            } else {
                host.appendChild(buildFrame(frameUrl(host)));
            }
        }
    }

    window.addEventListener("message", function (event) {
        if (!origin || event.origin !== origin) {
            return;
        }
        var data = event.data || {};
        if (data.tour_booking === "resize" && data.height) {
            var frames = document.querySelectorAll("iframe.tour-booking-frame");
            for (var i = 0; i < frames.length; i++) {
                if (frames[i].contentWindow === event.source) {
                    frames[i].style.height = Math.max(MIN_HEIGHT, data.height) + "px";
                }
            }
        } else if (data.tour_booking === "navigate" && data.url) {
            // Booking leaves the frame because a cross-origin frame has no
            // usable session. Checked rather than trusted: the origin test
            // above already says who sent this, and this says where it may
            // send the visitor, so a widget can never become a redirector.
            if (String(data.url).indexOf(origin + "/") === 0) {
                window.open(data.url, "_blank", "noopener");
            }
        }
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", mount);
    } else {
        mount();
    }
})();
