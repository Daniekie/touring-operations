"""Content for the website snippets.

The website editor saves the rendered DOM of a block, not the template that
produced it. A snippet that rendered its experiences server-side at drop time
would have them frozen into the page: a new experience would never show up, and
a price change would be visible everywhere except the block the operator
actually put on their home page.

So the blocks are shells and this hands them their markup on every page load.
Same fragments as the tour pages and the external embed — there is one copy of
the card and one copy of the booking widget, and this is one of the four things
that draw them.
"""

from odoo import http
from odoo.http import request

from .website import published_domain, tour_values


class TourBookingSnippet(http.Controller):

    @http.route(["/tour/snippet"], type="jsonrpc", auth="public", website=True)
    def snippet(self, widget=None, tour_id=None, columns=None, limit=None, **kwargs):
        """Render one snippet's content. -> {"html": str}

        Public, and reads through `sudo()` behind the published filter, because
        the visitor looking at the page is anonymous. Nothing here takes an
        instruction from the browser beyond which published records to draw:
        `widget` is matched against a fixed set, and an unknown one renders
        nothing rather than falling through to a default.
        """
        if widget in ("experiences", "button"):
            return {"html": self._render("tour_booking.experience_grid", {
                "tours": self._tours(limit),
                "columns": self._columns(columns),
            })}

        tour = self._tour(tour_id)
        if not tour:
            # Not an error: a block dropped a second ago has no experience
            # chosen yet, and the editor has to be able to draw it anyway.
            return {"html": ""}

        if widget == "experience":
            return {"html": self._render("tour_booking.experience_detail", dict(
                tour_values(tour, kwargs), embedded=True,
            ))}
        if widget == "book":
            return {"html": self._render(
                "tour_booking.booking_widget", tour_values(tour, kwargs)
            )}
        return {"html": ""}

    def _render(self, template, values):
        return request.env["ir.qweb"]._render(template, dict(values, request=request))

    def _tours(self, limit):
        try:
            limit = int(limit) or None
        except (TypeError, ValueError):
            limit = None
        return request.env["tour.tour"].sudo().search(published_domain(), limit=limit)

    def _tour(self, tour_id):
        try:
            tour = request.env["tour.tour"].sudo().browse(int(tour_id or 0)).exists()
        except (TypeError, ValueError):
            return None
        return tour if tour and tour.is_published else None

    def _columns(self, raw):
        try:
            return min(4, max(1, int(raw)))
        except (TypeError, ValueError):
            return 2
