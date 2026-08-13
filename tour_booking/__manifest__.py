{
    "name": "Tour Booking",
    "version": "19.0.1.0.0",
    "summary": "Day tours, boat trips and dives: departures, seats and direct bookings",
    "description": """
Tour Booking
============
A booking engine for operators who sell day experiences through their own
website — day tours, boat trips, scuba trips.

The model that matters: a departure is not a resource that gets blocked, it is
an inventory of seats that gets drawn down. One 09:00 boat with capacity 15
holds six separate bookings totalling 15 people, and availability is
`capacity - seats_sold` rather than a boolean.

* Tours with itineraries, meeting points, start times and content.
* Recurring availability rules that materialise into dated departures.
* Paid extras and checkout questions.
* Optional cancellation policies with refund windows.

There is deliberately no channel synchronisation with any OTA.
""",
    "author": "Cariflow",
    "website": "https://www.cariflow.com",
    "category": "Services/Tour Booking",
    "license": "LGPL-3",
    # `website` from the start: tours are published pages with their own slug,
    # and retrofitting the publishing mixins later is a schema change for no
    # gain. `payment` carries the provider-agnostic checkout; `account` is here
    # for `account.tax` only. `portal` sits under both and is declared because
    # the access-token pages lean on it.
    "depends": ["base", "mail", "website", "payment", "account", "portal"],
    "data": [
        "security/tour_booking_groups.xml",
        "security/ir.model.access.csv",
        "security/tour_booking_security.xml",
        "data/ir_sequence_data.xml",
        "data/ir_cron_data.xml",
        "views/tour_config_views.xml",
        "views/tour_tour_views.xml",
        "views/tour_availability_rule_views.xml",
        # Before the menus: the "Generate Departures" menu item resolves the
        # server action declared in here by id.
        "views/tour_departure_views.xml",
        "views/tour_booking_views.xml",
        "views/tour_booking_menus.xml",
        "views/website_templates.xml",
        # After website_templates: the checkout reuses the summary card and the
        # confirmation page links back to the tour page declared there.
        "views/website_checkout_templates.xml",
    ],
    "demo": [
        "demo/tour_demo.xml",
    ],
    "assets": {
        # Frontend only: none of this runs in the back office, and loading it
        # into the web client would cost every internal user the download.
        "web.assets_frontend": [
            "tour_booking/static/src/scss/tour_booking.scss",
            "tour_booking/static/src/js/tour_calendar.js",
        ],
    },
    "installable": True,
    "application": True,
}
