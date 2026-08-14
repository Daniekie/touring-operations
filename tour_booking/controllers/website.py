"""The public tour pages: the list, one tour, and its availability.

Routes are English because this is a redistributable module; Odoo's website
translation gives each language its own URL, so a Dutch site still gets a Dutch
path without the module hardcoding one.
"""

import calendar

from datetime import date, datetime, time

from odoo import fields, http
from odoo.http import request


def published_domain():
    # sudo() is used to read tours for anonymous visitors, so the published
    # flag has to be the access rule. It is applied here, once, rather than
    # trusted to each caller.
    return [("is_published", "=", True)]


def month_of(raw):
    """The month the calendar should open on. -> date (first of month).

    Anything unparseable degrades to the current month rather than to an error
    page: a mangled query string should still show a bookable calendar.
    """
    today = fields.Date.context_today(request.env["tour.tour"])
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m").date().replace(day=1)
        except ValueError:
            pass
    return today.replace(day=1)


def tour_values(tour_sudo, kwargs):
    """The tour page, plus whatever choice the guest arrived with.

    A guest who pressed Book now inside an embedded frame is sent to the tour
    page — on the operator's own domain, where the session and the CSRF token
    work — with their departure and party size in the query string. Reading them
    back means they choose once rather than twice.

    Nothing is created here. This is a GET, and a GET that made a booking would
    fire for every crawler and link preview that touched the URL; the booking is
    still made by the ordinary POST to `/tour/book`.

    A module-level function rather than a controller method so the embed
    controller can use it without inheriting a class whose routes it does not
    want.
    """
    preselect = _preselected_departure(tour_sudo, kwargs.get("departure_id"))
    month = month_of(kwargs.get("month"))
    if preselect:
        # Open on the departure's own month, or the widget loads a month that
        # does not contain the thing it is meant to select.
        month = preselect.date.replace(day=1)
    return {
        "tour": tour_sudo,
        "month": month,
        "preselect_departure": preselect.id if preselect else None,
        "preselect_pax": _preselected_pax(kwargs.get("pax")),
        "autobook": bool(preselect) and kwargs.get("autobook") in ("1", "true"),
    }


def _preselected_departure(tour_sudo, raw):
    """The departure named in the URL, if it is one this tour can still sell."""
    try:
        departure = request.env["tour.departure"].sudo().browse(int(raw or 0)).exists()
    except (TypeError, ValueError):
        return None
    if not departure or departure.tour_id != tour_sudo:
        return None
    if departure.seats_available <= 0 or not departure._is_bookable():
        return None
    return departure


def _preselected_pax(raw):
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return None


class TourBookingWebsite(http.Controller):

    def _published_domain(self):
        return published_domain()

    @http.route(["/tours"], type="http", auth="public", website=True, sitemap=True)
    def tours(self, **kwargs):
        """The catalogue.

        Cards carry the real per-person price rather than a "from" price: this
        module has one price per tour, so a "from" would be a hedge against a
        variation that cannot exist.
        """
        tours = request.env["tour.tour"].sudo().search(self._published_domain())
        return request.render("tour_booking.tours", {"tours": tours})

    @http.route(
        ['/tour/<model("tour.tour"):tour>'],
        type="http",
        auth="public",
        website=True,
        sitemap=True,
    )
    def tour(self, tour, **kwargs):
        if not tour.sudo().is_published:
            return request.not_found()
        tour_sudo = tour.sudo()
        return request.render(
            "tour_booking.tour_detail",
            dict(tour_values(tour_sudo, kwargs), extras=tour_sudo.extra_ids),
        )

    def _month_of(self, raw):
        return month_of(raw)

    @http.route(
        ["/tour/<int:tour_id>/availability"],
        type="jsonrpc",
        auth="public",
        website=True,
    )
    def availability(self, tour_id, month=None, **kwargs):
        """The bookable dates of one month. -> {"days": {...}}

        One month at a time on purpose: the widget shows one month, and sending
        a year of departures to render twenty-eight cells is a lot of data for a
        page that will mostly be read on a phone.

        A date appears only when a departure is open, has seats left, and is
        still inside the cut-off. Filtering here rather than in the browser
        means the rule that decides what is bookable lives in exactly one place
        — the same one the booking itself is checked against.
        """
        tour = request.env["tour.tour"].sudo().browse(tour_id).exists()
        if not tour or not tour.is_published:
            return {"days": {}}

        first = self._month_of(month)
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        now = fields.Datetime.now()

        departures = request.env["tour.departure"].sudo().search([
            ("tour_id", "=", tour.id),
            ("date", ">=", first),
            ("date", "<=", last),
            ("state", "in", ("open", "full")),
        ], order="start_datetime")

        days = {}
        for departure in departures:
            if departure.seats_available <= 0 or not departure._is_bookable(now):
                continue
            days.setdefault(departure.date.isoformat(), []).append({
                "id": departure.id,
                # The tour's timezone, never the visitor's: a 09:00 dive is at
                # 09:00 on the dock whether you book it from Bonaire or Berlin.
                "time": departure._local_start().strftime("%H:%M")
                        if tour.has_specific_time else None,
                "seats_available": departure.seats_available,
                "min_pax": departure.min_pax,
                "max_pax": departure.max_pax,
            })
        return {
            "days": days,
            "month": first.strftime("%Y-%m"),
            "has_specific_time": tour.has_specific_time,
        }
