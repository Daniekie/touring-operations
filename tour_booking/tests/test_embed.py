"""Putting the widgets on somebody else's website.

The design being defended here: a cross-origin iframe gets no Odoo session
cookie, so the booking cannot be submitted from inside one. Browsing happens in
the frame and the booking escapes to a first-party page. Most of these tests are
about that boundary holding.
"""

import json
import re

from odoo.tests import tagged
from odoo.tests.common import HttpCase

from .common import TourCase


@tagged("post_install", "-at_install")
class TestEmbed(HttpCase, TourCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tour.is_published = True
        cls.hidden = cls.env["tour.tour"].create({
            "name": "Staff Trip",
            "duration_hours": 2.0,
            "default_capacity": 6,
            "price_per_person": 10.0,
            "is_published": False,
        })

    # --- The loader ---------------------------------------------------------

    def test_the_embed_loader_is_served_as_javascript_to_any_origin(self):
        """It is fetched by a script tag on a site we know nothing about, so it
        has to be reachable without a session and without an Origin we trust."""
        response = self.url_open("/tour/embed.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["Content-Type"])
        self.assertIn("data-tour-widget", response.text)

    def test_the_loader_does_not_mint_a_session_for_every_visitor(self):
        """It is requested once per page view on other people's sites. A session
        row for each of those is a session store full of nothing."""
        response = self.url_open("/tour/embed.js")

        self.assertNotIn("session_id", response.headers.get("Set-Cookie", ""))

    # --- The framed pages ---------------------------------------------------

    def test_the_experiences_frame_renders_without_site_chrome(self):
        response = self.url_open("/tour/embed/experiences")

        self.assertEqual(response.status_code, 200)
        self.assertIn("o_tour_embed", response.text)
        self.assertIn(self.tour.name, response.text)
        self.assertNotIn('id="top_menu"', response.text)

    def test_the_booking_box_frame_is_only_the_booking_box(self):
        """The widget for a site that has already written its own product page:
        no picture, no description, just somewhere to choose a date."""
        response = self.url_open("/tour/embed/book/%s" % self.tour.id)

        self.assertEqual(response.status_code, 200)
        self.assertIn("o_tour_widget", response.text)
        self.assertNotIn("o_tour_experience_detail", response.text)

    def test_an_unpublished_experience_is_not_reachable_through_the_embed(self):
        """`sudo()` is used throughout the embed to read for anonymous visitors,
        so the published flag is the only access check there is."""
        for route in ("experience", "book"):
            response = self.url_open("/tour/embed/%s/%s" % (route, self.hidden.id))
            self.assertEqual(response.status_code, 404, route)

    def test_the_embed_urls_do_not_redirect(self):
        """Ids rather than slugs. This URL gets pasted into somebody's template
        and left there: a slug costs a redirect on every load and breaks the
        moment the experience is renamed."""
        response = self.url_open(
            "/tour/embed/experience/%s" % self.tour.id, allow_redirects=False
        )

        self.assertEqual(response.status_code, 200)

    # --- Who may frame it ---------------------------------------------------

    def test_any_site_may_frame_the_widgets_by_default(self):
        """The content is a public catalogue. A lock that has to be configured
        before the feature works is a lock people switch off."""
        response = self.url_open("/tour/embed/experiences")

        self.assertNotIn("Content-Security-Policy", response.headers)
        self.assertNotIn("X-Frame-Options", response.headers)

    def test_an_allow_list_is_published_as_frame_ancestors(self):
        self.env.company.tour_embed_domains = "https://example.com, https://www.example.com"
        self.env.flush_all()

        response = self.url_open("/tour/embed/experiences")

        self.assertEqual(
            response.headers.get("Content-Security-Policy"),
            "frame-ancestors https://example.com https://www.example.com",
        )

    def test_a_junk_entry_in_the_allow_list_does_not_take_the_page_down(self):
        """The setting is a free-text field an operator types into.

        Whatever they type went into a response header unchecked. A newline in
        there is a header Werkzeug refuses to send — a 500 on the widget, for a
        typo in a settings field, with nothing on the page saying which setting
        caused it.
        """
        self.env.company.tour_embed_domains = "https://good.example.com, not a domain\nx"
        self.env.flush_all()

        response = self.url_open("/tour/embed/experiences")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Content-Security-Policy"),
            "frame-ancestors https://good.example.com",
            "The usable entry should survive and the junk should be dropped.",
        )

    def test_an_allow_list_of_nothing_but_junk_frames_nobody(self):
        """Not "anybody": an operator who filled this in wanted a restriction,
        and falling back to the open default because their typing was unusable
        is the one interpretation they did not ask for."""
        self.env.company.tour_embed_domains = "nonsense, also nonsense"
        self.env.flush_all()

        response = self.url_open("/tour/embed/experiences")

        self.assertEqual(
            response.headers.get("Content-Security-Policy"),
            "frame-ancestors 'none'",
        )

    # --- The boundary the whole design exists for ---------------------------

    def test_a_choice_made_in_a_frame_is_restored_on_the_first_party_page(self):
        """What Book now does: hands the departure and the party size to the
        host page, which opens the tour on the operator's own domain. The page
        has to arrive already knowing what was chosen, or the guest picks twice.
        """
        departure = self._departure()

        response = self.url_open("%s?departure_id=%s&pax=3&autobook=1" % (
            self.tour.website_url, departure.id,
        ))

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-preselect-departure="%s"' % departure.id, response.text)
        self.assertIn('data-preselect-pax="3"', response.text)
        self.assertIn('data-autobook="1"', response.text)

    def test_a_departure_belonging_to_another_experience_is_ignored(self):
        """The departure arrives in a query string, which is to say from a
        stranger. It is only honoured if this tour can actually sell it."""
        # Date-only, so it can be published without start times.
        other = self.env["tour.tour"].create({
            "name": "Other", "duration_hours": 1.0, "default_capacity": 4,
            "price_per_person": 5.0, "is_published": True,
            "has_specific_time": False,
        })
        foreign = self._departure(tour_id=other.id)

        response = self.url_open(
            "%s?departure_id=%s" % (self.tour.website_url, foreign.id)
        )

        self.assertNotIn("data-preselect-departure", response.text)

    def test_a_departure_that_can_no_longer_be_sold_is_not_preselected(self):
        """The frame offered it a moment ago; by the time the tab opens it may
        be gone. Restoring a dead choice puts the guest in front of a Book now
        button that will refuse them."""
        sold_out = self._departure(capacity=2)
        self._booking(departure=sold_out, pax=2)

        response = self.url_open(
            "%s?departure_id=%s" % (self.tour.website_url, sold_out.id)
        )

        self.assertNotIn("data-preselect-departure", response.text)

    def test_a_cancelled_departure_is_not_preselected(self):
        cancelled = self._departure()
        cancelled.action_cancel()

        response = self.url_open(
            "%s?departure_id=%s" % (self.tour.website_url, cancelled.id)
        )

        self.assertNotIn("data-preselect-departure", response.text)

    def test_a_nonsense_departure_is_ignored_rather_than_raising(self):
        """A mangled query string should still show a bookable calendar, not an
        error page."""
        for raw in ("abc", "-1", "0", "999999999"):
            response = self.url_open(
                "%s?departure_id=%s" % (self.tour.website_url, raw)
            )
            self.assertEqual(response.status_code, 200, raw)
            self.assertNotIn("data-preselect-departure", response.text)

    def test_a_nonsense_party_size_is_ignored(self):
        departure = self._departure()

        response = self.url_open("%s?departure_id=%s&pax=%s" % (
            self.tour.website_url, departure.id, "-4",
        ))

        self.assertIn('data-preselect-pax="1"', response.text)

    def test_autobook_is_ignored_without_a_departure_to_book(self):
        """Otherwise a bare `?autobook=1` tells the page to submit a form that
        has nothing selected in it."""
        response = self.url_open("%s?autobook=1" % self.tour.website_url)

        self.assertNotIn("data-autobook", response.text)

    def test_arriving_with_a_preselection_creates_nothing(self):
        """A GET that made a booking would fire for every crawler and link
        preview that touched the URL, and every one of those would hold seats."""
        departure = self._departure()
        before = self.env["tour.booking"].search_count([])

        self.url_open("%s?departure_id=%s&pax=2&autobook=1" % (
            self.tour.website_url, departure.id,
        ))

        self.assertEqual(self.env["tour.booking"].search_count([]), before)

    # --- The snippet feed ---------------------------------------------------

    def test_the_snippet_feed_renders_the_same_cards_as_the_catalogue(self):
        """The website blocks fetch their markup rather than rendering it once
        at drop time, so this is what an operator's home page actually shows."""
        result = self._rpc("/tour/snippet", {"widget": "experiences", "columns": "3"})

        self.assertIn("o_tour_card", result["html"])
        self.assertIn(self.tour.name, result["html"])
        self.assertIn("col-lg-4", result["html"])

    def test_two_columns_do_not_wait_for_a_desktop_breakpoint(self):
        """A media query inside an iframe measures the frame, not the screen.

        This grid spends its life in a frame or a page column. `col-lg-6` needs
        992 pixels, which a 900-pixel column on somebody's website does not
        have — so an operator who asks for two columns gets one, on a desktop
        monitor, and it looks like the widget is broken. It was.
        """
        result = self._rpc("/tour/snippet", {"widget": "experiences", "columns": "2"})

        self.assertIn("col-md-6", result["html"])
        self.assertNotIn("col-lg-6", result["html"])

    def test_a_junk_column_count_falls_back_rather_than_failing(self):
        """It comes off an attribute in the page's own markup, which an operator
        can edit by hand."""
        for raw in ("99", "-3", "two", ""):
            result = self._rpc(
                "/tour/snippet", {"widget": "experiences", "columns": raw}
            )
            self.assertIn("o_tour_card", result["html"], raw)

    def test_the_limit_caps_how_many_cards_a_block_draws(self):
        self.env["tour.tour"].create({
            "name": "Second", "duration_hours": 1.0, "default_capacity": 4,
            "price_per_person": 5.0, "is_published": True, "has_specific_time": False,
        })

        result = self._rpc("/tour/snippet", {"widget": "experiences", "limit": "1"})

        self.assertEqual(result["html"].count("o_tour_card"), 1)

    def test_a_junk_limit_shows_everything_rather_than_nothing(self):
        """An unreadable limit must not be read as zero: a block that silently
        shows no experiences looks exactly like a broken one."""
        result = self._rpc("/tour/snippet", {"widget": "experiences", "limit": "lots"})

        self.assertIn("o_tour_card", result["html"])

    def test_a_card_in_a_frame_keeps_the_visitor_in_the_frame(self):
        """The operator embedded a catalogue to keep people on their own page.
        A card that opened a new tab on our site would undo the one thing they
        wanted, so browsing stays in the frame — only Book now leaves."""
        framed = self.url_open("/tour/embed/experiences").text

        self.assertIn("/tour/embed/experience/%s?from=list" % self.tour.id, framed)
        self.assertEqual(self._card_targets(framed), {"_self"})

    def test_a_card_on_the_website_goes_to_the_tour_page(self):
        """The same fragment, on our own site, where the frame does not exist."""
        onsite = self.url_open("/tours").text

        self.assertIn(self.tour.website_url, onsite)
        self.assertNotIn("/tour/embed/", onsite)
        self.assertEqual(self._card_targets(onsite), {"_self"})

    def test_a_visitor_who_browsed_into_an_experience_can_get_back(self):
        """There is no browser chrome inside an iframe. Without this the guest
        is stranded on whichever card they clicked."""
        arrived = self.url_open(
            "/tour/embed/experience/%s?from=list" % self.tour.id
        ).text

        self.assertIn("/tour/embed/experiences", arrived)

    def test_an_experience_embedded_on_its_own_offers_no_way_out(self):
        """An operator who embedded one experience deliberately did not ask for
        a link to their competitors' worth of other ones."""
        direct = self.url_open("/tour/embed/experience/%s" % self.tour.id).text

        self.assertNotIn('href="/tour/embed/experiences"', direct)

    def _card_targets(self, html):
        """Every `target` on a link pointing at a tour. -> set[str]"""
        return set(re.findall(r'<a[^>]*href="/tour/[^"]*"[^>]*target="([^"]*)"', html))

    def test_the_snippet_feed_refuses_an_unpublished_experience(self):
        result = self._rpc(
            "/tour/snippet", {"widget": "book", "tour_id": self.hidden.id}
        )

        self.assertEqual(result["html"], "")

    def test_a_block_with_no_experience_chosen_renders_nothing_rather_than_failing(self):
        """A block dropped a second ago has nothing set. The editor still has to
        be able to draw it."""
        result = self._rpc("/tour/snippet", {"widget": "experience"})

        self.assertEqual(result["html"], "")

    def test_an_unknown_widget_name_renders_nothing(self):
        """`widget` arrives from the page's own markup, which an operator can
        edit. It is matched against a fixed set rather than falling through to
        a default."""
        result = self._rpc("/tour/snippet", {"widget": "../../etc/passwd"})

        self.assertEqual(result["html"], "")

    # --- Helpers ------------------------------------------------------------

    def _rpc(self, route, params):
        response = self.url_open(
            route,
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": params}),
            headers={"Content-Type": "application/json"},
        )
        return response.json()["result"]
