"""Putting the booking on somebody else's website.

An operator who keeps their WordPress or Squarespace site still wants the
booking to appear inside it. They paste one script tag and a marker div; the
script draws an iframe pointing back here.

The shape of the thing is decided by one browser fact. Odoo sets its session
cookie with no `SameSite` attribute, which browsers treat as `SameSite=Lax` and
therefore do not send inside a cross-origin frame; Safari and Firefox refuse the
cookie outright. With no session there is no usable CSRF token, so a booking
POSTed from the frame is rejected — and payment providers largely refuse to be
framed anyway.

So the frame is for *browsing* only. Pressing Book now hands a first-party URL
up to the host page, which opens it on the operator's own domain, where the
session, the token and the payment redirect all behave normally. One extra tab,
in exchange for a checkout that works in every browser.
"""

from odoo import http
from odoo.http import request

from .website import published_domain, tour_values


class TourBookingEmbed(http.Controller):

    # --- The loader ---------------------------------------------------------

    @http.route(
        ["/tour/embed.js"], type="http", auth="public", cors="*", save_session=False
    )
    def loader(self, **kwargs):
        """The script an operator pastes into their own site.

        Served from a route rather than linked at its `/tour_booking/static/...`
        path so the URL somebody copies into a template stays stable if the file
        ever moves, and so it can never be mistaken for an internal asset.

        `save_session` is off: this is a static asset fetched by anonymous
        visitors on other people's pages, and minting a session row for each of
        them would fill the session store for nothing.
        """
        stream = http.Stream.from_path(
            "tour_booking/static/src/js/embed_loader.js", filter_ext=(".js",)
        )
        response = stream.get_response(mimetype="text/javascript")
        # Short, but not zero: the loader changes with the module, and an
        # operator who pastes it once should not be stuck with a year-old copy.
        response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    # --- The framed pages ---------------------------------------------------

    def _embed_response(self, template, values):
        """Render a page meant to live inside somebody else's iframe.

        `website.layout` is kept — it carries the frontend asset bundle the
        calendar needs — with its header and footer switched off, so the frame
        holds the widget and nothing that belongs to a full site.
        """
        response = request.render(template, dict(
            values,
            no_header=True,
            no_footer=True,
            # `embedded` keeps a card's link inside the frame, on the embedded
            # version of the experience. `link_target` governs everything else —
            # Full details and the like — which does have to leave, because a
            # whole tour page rendered in a 600-pixel box is unreadable.
            embedded=True,
            link_target="_blank",
        ))
        return self._restrict_framing(response)

    def _restrict_framing(self, response):
        """Say who may frame this, when the operator has said.

        Odoo sets no `X-Frame-Options` on ordinary website routes, so these
        pages are already framable. An operator who wants to be embedded only by
        their own site fills in the allow-list and gets a `frame-ancestors`
        header; an empty list means anybody, which is the default because the
        content here is a public catalogue.
        """
        domains = request.env.company.sudo().tour_embed_domains
        if domains:
            allowed = " ".join(d.strip() for d in domains.split(",") if d.strip())
            if allowed:
                response.headers["Content-Security-Policy"] = (
                    "frame-ancestors %s" % allowed
                )
        return response

    @http.route(
        ["/tour/embed/experiences"], type="http", auth="public", website=True,
        sitemap=False,
    )
    def experiences(self, **kwargs):
        """Widget 1: the catalogue."""
        tours = request.env["tour.tour"].sudo().search(published_domain())
        return self._embed_response("tour_booking.embed_experiences", {
            "tours": tours,
            "columns": self._columns(kwargs.get("columns")),
        })

    def _columns(self, raw):
        """How wide the host's container is, is the host's business. The default
        of two matches the module's own catalogue page."""
        try:
            return min(4, max(1, int(raw)))
        except (TypeError, ValueError):
            return 2

    # Plain ids, not the slug converter the public pages use. These URLs are
    # generated from an id and pasted into somebody's template, where they will
    # sit for years: a slug redirects on every single load, and it changes the
    # moment an experience is renamed. `sitemap=False` for the same reason —
    # the page that should be indexed is the tour's own.
    def _tour_or_404(self, tour_id):
        tour = request.env["tour.tour"].sudo().browse(tour_id).exists()
        return tour if tour and tour.is_published else None

    @http.route(
        ["/tour/embed/experience/<int:tour_id>"],
        type="http", auth="public", website=True, sitemap=False,
    )
    def experience(self, tour_id, **kwargs):
        """Widget 2: one experience — picture, description, calendar."""
        tour = self._tour_or_404(tour_id)
        if not tour:
            return request.not_found()
        return self._embed_response("tour_booking.embed_experience", dict(
            tour_values(tour, kwargs),
            # Set by the catalogue's own cards, so the back link appears only
            # for somebody who actually came from a catalogue.
            from_list=kwargs.get("from") == "list",
        ))

    @http.route(
        ["/tour/embed/book/<int:tour_id>"],
        type="http", auth="public", website=True, sitemap=False,
    )
    def book(self, tour_id, **kwargs):
        """Widget 3: the booking box on its own.

        For an operator who has already written their own product page and
        wants nothing from us but somewhere to choose a date and press Book.
        """
        tour = self._tour_or_404(tour_id)
        if not tour:
            return request.not_found()
        return self._embed_response(
            "tour_booking.embed_book", tour_values(tour, kwargs)
        )
