"""Can an operator find the page they just made?

Creating an experience creates a website page, and for a long time nothing in
Odoo said so. The page is not in the website editor's page list, there is no
"add a page" step anywhere, and the address is a slug nobody typed — so the
honest answer to "where is my tour page?" was "read the source". These check the
three places that now answer it: the record's chatter, the confirmation after
creating one, and the form itself.
"""

from odoo.tests.common import TransactionCase


class TestPageUrl(TransactionCase):

    def _tour(self, **overrides):
        values = {
            "name": "Sunset Sail",
            "duration_hours": 2.0,
            "default_capacity": 8,
            "price_per_person": 40.0,
            "has_specific_time": False,
        }
        values.update(overrides)
        return self.env["tour.tour"].create(values)

    # --- The address --------------------------------------------------------

    def test_the_page_address_is_the_whole_url(self):
        """A path is not something an operator can send to anybody."""
        self.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://tours.example.com"
        )
        tour = self._tour()

        self.assertTrue(tour.website_url.startswith("/tour/"))
        self.assertEqual(
            tour.website_full_url, "https://tours.example.com" + tour.website_url
        )

    def test_a_trailing_slash_on_the_base_url_does_not_double_up(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://tours.example.com/"
        )
        tour = self._tour()

        self.assertNotIn("//tour/", tour.website_full_url)

    def test_a_form_being_filled_in_has_no_page_yet(self):
        """The address is shown on the form, so it is computed for a record
        that does not exist yet. A `NewId` has no page, and slugging one
        produces an address that goes nowhere — better empty than wrong.
        """
        draft = self.env["tour.tour"].new({"name": "Not saved"})

        self.assertFalse(draft.website_url)
        self.assertFalse(draft.website_full_url)

    def test_renaming_moves_the_address(self):
        """Which is why it is shown rather than written down once. Old links
        still work — the route resolves on the id at the end of the slug — but
        the address an operator copies today is not the one from last month."""
        tour = self._tour()
        before = tour.website_url

        tour.name = "Sunset Sail And Snorkel"

        self.assertNotEqual(tour.website_url, before)
        self.assertIn("snorkel", tour.website_url.lower())

    # --- Being told ---------------------------------------------------------

    def test_creating_an_experience_records_its_page_in_the_chatter(self):
        """The copy that is still there next month, unlike the toast."""
        tour = self._tour()

        bodies = tour.message_ids.mapped("body")
        self.assertTrue(
            any(tour.website_url in body for body in bodies),
            "Nothing in the chatter says where the page is: %s" % bodies,
        )

    def test_confirming_a_new_experience_hands_over_the_url(self):
        tour = self._tour()

        action = tour.action_confirm()

        self.assertEqual(action["tag"], "display_notification")
        params = action["params"]
        self.assertEqual(params["links"][0]["url"], tour.website_url)
        self.assertEqual(params["links"][0]["label"], tour.website_full_url)
        # `%s` is where the link is substituted. Without it the address is
        # silently dropped and the notification says nothing at all.
        self.assertIn("%s", params["message"])
        # A URL that fades after four seconds has not been handed to anybody.
        self.assertTrue(params["sticky"])

    def test_an_unpublished_experience_is_told_its_page_is_not_live_yet(self):
        """The page 404s for visitors until it is published, so a bare "here is
        your page" would be a link the operator opens and finds broken."""
        tour = self._tour(is_published=False)

        message = tour.action_confirm()["params"]["message"]

        self.assertIn("publish", message.lower())

    def test_a_published_experience_is_not_told_to_publish_it(self):
        tour = self._tour()
        self.assertTrue(tour.is_published)

        message = tour.action_confirm()["params"]["message"]

        self.assertNotIn("publish", message.lower())

    # --- Going live ---------------------------------------------------------

    def test_a_new_experience_is_published(self):
        """An experience is filled in so that it can be sold, so publishing it
        was a step people forgot rather than a decision they made — and the
        page they had just been handed the address of answered 404."""
        tour = self._tour()

        self.assertTrue(tour.is_published)

    def test_one_that_could_not_be_booked_yet_is_left_alone(self):
        """Start times switched on with none defined produces no departures,
        so publishing it would put up a page with nothing to book on it. The
        constraint refuses that, and creating a tour must not hit it."""
        tour = self._tour(has_specific_time=True)

        self.assertFalse(tour.is_published)

    def test_an_experience_asked_to_stay_down_stays_down(self):
        """What the demo data and a duplicate pass — an explicit value is a
        decision, and publishing over it would undo one."""
        tour = self._tour(is_published=False)

        self.assertFalse(tour.is_published)

    # --- Being shown --------------------------------------------------------

    def test_the_form_and_the_list_show_the_address(self):
        """Browsing is the other half of the question. An operator who wants to
        check a page exists is not going to open eight records to find out."""
        form = self.env.ref("tour_booking.tour_tour_view_form").arch
        self.assertIn('name="website_full_url"', form)

        listing = self.env.ref("tour_booking.tour_tour_view_list").arch
        self.assertIn('name="website_url"', listing)

        kanban = self.env.ref("tour_booking.tour_tour_view_kanban").arch
        self.assertIn('name="website_url"', kanban)
