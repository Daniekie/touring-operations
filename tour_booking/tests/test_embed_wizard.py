"""The screen that hands an operator their embed code.

Worth testing carefully for an unglamorous reason: whatever this produces gets
pasted into a template on another website and left there. A wrong URL or a
missing id is not a bug somebody notices in the back office — it is a blank
space on a customer's home page that nobody reports for a month.
"""

from .common import TourCase


class TestEmbedWizard(TourCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tour.is_published = True
        cls.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://tours.example.com/"
        )

    def _wizard(self, **values):
        return self.env["tour.embed"].create(values)

    def test_the_code_points_at_this_instance(self):
        """Built from `web.base.url`, not from the request: the operator may be
        reading this page through a proxy hostname their customers cannot
        reach."""
        code = self._wizard(widget_type="experiences").code

        self.assertIn('src="https://tours.example.com/tour/embed.js"', code)

    def test_a_trailing_slash_on_the_base_url_does_not_double_up(self):
        """`web.base.url` is entered by a human and often ends in a slash."""
        code = self._wizard(widget_type="experiences").code

        self.assertNotIn("//tour/embed.js", code)

    def test_the_catalogue_code_carries_no_experience(self):
        code = self._wizard(widget_type="experiences", tour_id=self.tour.id).code

        self.assertIn('data-tour-widget="experiences"', code)
        self.assertNotIn("data-tour-id", code)

    def test_the_experience_code_names_the_experience(self):
        code = self._wizard(widget_type="experience", tour_id=self.tour.id).code

        self.assertIn('data-tour-widget="experience"', code)
        self.assertIn('data-tour-id="%s"' % self.tour.id, code)

    def test_the_booking_box_code_names_the_experience(self):
        code = self._wizard(widget_type="book", tour_id=self.tour.id).code

        self.assertIn('data-tour-widget="book"', code)
        self.assertIn('data-tour-id="%s"' % self.tour.id, code)

    def test_the_button_carries_its_label(self):
        code = self._wizard(widget_type="button", label="Reserve a seat").code

        self.assertIn('data-tour-label="Reserve a seat"', code)

    def test_the_preview_opens_the_widget_that_was_generated(self):
        """The preview and the code have to describe the same thing, or an
        operator approves one widget and ships another."""
        for kind, expected in [
            ("experiences", "/tour/embed/experiences"),
            ("experience", "/tour/embed/experience/%s" % self.tour.id),
            ("book", "/tour/embed/book/%s" % self.tour.id),
            # A button has no page of its own — it opens the catalogue.
            ("button", "/tour/embed/experiences"),
        ]:
            wizard = self._wizard(widget_type=kind, tour_id=self.tour.id)
            self.assertIn(expected, wizard.preview_url, kind)

    def test_an_experience_widget_with_nothing_chosen_has_no_preview(self):
        """The Preview button hides rather than opening a 404."""
        wizard = self._wizard(widget_type="experience")

        self.assertFalse(wizard.preview_url)

    def test_the_code_changes_when_the_experience_does(self):
        """`code` is computed, and a stale one is a wrong one that looks right."""
        wizard = self._wizard(widget_type="experience", tour_id=self.tour.id)
        other = self.env["tour.tour"].create({
            "name": "Second", "duration_hours": 1.0, "default_capacity": 4,
            "price_per_person": 5.0, "is_published": True, "has_specific_time": False,
        })

        wizard.tour_id = other

        self.assertIn('data-tour-id="%s"' % other.id, wizard.code)

    def test_only_published_experiences_are_offered(self):
        """An unpublished one is served as a 404 to the public, so offering it
        here is offering a widget that renders nothing."""
        domain = self.env["tour.embed"]._fields["tour_id"].domain

        self.assertIn(("is_published", "=", True), domain)

    def test_the_share_button_opens_the_wizard_on_this_experience(self):
        action = self.tour.action_share()

        self.assertEqual(action["res_model"], "tour.embed")
        self.assertEqual(action["context"]["default_tour_id"], self.tour.id)
        self.assertEqual(action["context"]["default_widget_type"], "experience")
