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
        "views/tour_calendar_views.xml",
        "views/tour_embed_views.xml",
        "views/tour_booking_menus.xml",
        "views/res_config_settings_views.xml",
        # The fragments first: everything below draws the public markup by
        # calling into them, and a template cannot be called before it exists.
        "views/website_fragments.xml",
        "views/website_templates.xml",
        "views/website_embed_templates.xml",
        "views/snippets/tour_snippets.xml",
        # After website_templates: the checkout reuses the summary card and the
        # confirmation page links back to the tour page declared there.
        "views/website_checkout_templates.xml",
        # Last: it builds the website menu from whatever is published, so it
        # wants the rest of the module already in place.
        "data/website_menu_data.xml",
    ],
    "demo": [
        "demo/tour_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "tour_booking/static/src/scss/tour_booking_backend.scss",
            "tour_booking/static/src/scss/booking_calendar.scss",
            "tour_booking/static/src/js/booking_calendar/booking_calendar.js",
            "tour_booking/static/src/js/booking_calendar/booking_calendar.xml",
        ],
        # Frontend only: none of this runs in the back office, and loading it
        # into the web client would cost every internal user the download.
        "web.assets_frontend": [
            "tour_booking/static/src/scss/tour_booking.scss",
            "tour_booking/static/src/scss/tour_embed.scss",
            "tour_booking/static/src/js/interactions/tour_calendar.js",
            "tour_booking/static/src/js/interactions/tour_checkout.js",
            "tour_booking/static/src/js/interactions/tour_gallery.js",
            "tour_booking/static/src/js/interactions/tour_snippet.js",
            "tour_booking/static/src/js/interactions/embed_frame.js",
            # `*.edit.js` is deliberately absent: it registers against the
            # builder, which a visitor does not have. Listing these files one
            # by one rather than by glob is what keeps it out.
        ],
        # Inside the builder's iframe, which is where a block being edited
        # lives. Without this the blocks draw nothing until the page is saved.
        "website.assets_inside_builder_iframe": [
            "tour_booking/static/src/js/interactions/*.edit.js",
        ],
        # The option panels for the booking blocks. Editor-only, so they cost
        # a visitor nothing.
        "website.website_builder_assets": [
            "tour_booking/static/src/website_builder/**/*",
        ],
        # The loader is deliberately absent from every bundle. It runs on other
        # people's websites, where there is no Odoo to bundle it, and it is
        # served as a plain file by `/tour/embed.js`.
    },
    "installable": True,
    "application": True,
}
