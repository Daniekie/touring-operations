"""The Tours menu, kept in step with the experiences.

The menu is generated, which makes it a thing that can silently disagree with
the catalogue: an entry pointing at an unpublished tour is a 404 on somebody's
front page, and a stale entry after a rename is a link that goes to the right
place with the wrong words on it. Every test here is one way the two can drift.
"""

from odoo.tests.common import TransactionCase


class TestWebsiteMenu(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.website = cls.env["website"].search([], limit=1)
        cls.env.company.tour_auto_menu = True

    def _tour(self, published=True, **overrides):
        values = {
            "name": "Sunset Sail",
            "duration_hours": 2.0,
            "default_capacity": 8,
            "price_per_person": 40.0,
            "has_specific_time": False,
            "is_published": published,
        }
        values.update(overrides)
        return self.env["tour.tour"].create(values)

    # Scoped to one website on purpose. A database with demo data has two, and
    # each gets its own menu — so an unscoped search finds two of everything
    # and says nothing about whether either menu is right.
    def _entry(self, tour):
        return self.env["website.menu"].search([
            ("tour_id", "=", tour.id), ("website_id", "=", self.website.id),
        ])

    def _kind(self, kind):
        return self.env["website.menu"].search([
            ("tour_menu", "=", kind), ("website_id", "=", self.website.id),
        ])

    def _root(self):
        return self._kind("root")

    # --- Appearing ----------------------------------------------------------

    def test_publishing_a_tour_puts_it_in_the_menu(self):
        tour = self._tour()

        entry = self._entry(tour)

        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.name, "Sunset Sail")
        self.assertEqual(entry.url, tour.website_url)

    def test_the_entries_hang_under_a_tours_heading(self):
        tour = self._tour()

        root = self._root()

        self.assertTrue(root, "There is no Tours heading.")
        self.assertEqual(self._entry(tour).parent_id, root)

    def test_the_catalogue_is_the_first_entry_under_the_heading(self):
        """Odoo forces a menu with children to "#" — a heading with a dropdown
        opens the dropdown instead of navigating. So /tours needs an entry of
        its own, or publishing the first tour makes the catalogue unreachable
        from the menu."""
        tour = self._tour()

        catalog = self._kind("catalog")

        self.assertEqual(catalog.url, "/tours")
        self.assertEqual(catalog.parent_id, self._root())
        self.assertLess(
            catalog.sequence, self._entry(tour).sequence,
            "The way to see everything is buried under the tours.",
        )

    def test_an_unpublished_tour_stays_out(self):
        """Its page answers 404. A menu entry that 404s is worse than none."""
        tour = self._tour(published=False)

        self.assertFalse(self._entry(tour))

    def test_publishing_later_adds_it(self):
        tour = self._tour(published=False)

        tour.is_published = True

        self.assertTrue(self._entry(tour))

    # --- Keeping up ---------------------------------------------------------

    def test_unpublishing_takes_it_back_out(self):
        tour = self._tour()

        tour.is_published = False

        self.assertFalse(self._entry(tour))

    def test_renaming_a_tour_renames_the_entry_and_moves_its_link(self):
        """The slug carries the name, so a rename changes both. An entry that
        kept the old name would be a link with the wrong words on it."""
        tour = self._tour()
        old_url = self._entry(tour).url

        tour.name = "Sunset Sail And Snorkel"

        entry = self._entry(tour)
        self.assertEqual(entry.name, "Sunset Sail And Snorkel")
        self.assertEqual(entry.url, tour.website_url)
        self.assertNotEqual(entry.url, old_url)

    def test_deleting_a_tour_takes_its_entry_with_it(self):
        tour = self._tour()
        self.assertTrue(self._entry(tour))

        tour.unlink()

        self.assertFalse(self.env["website.menu"].search([
            ("name", "=", "Sunset Sail"), ("website_id", "=", self.website.id),
        ]))

    def test_archiving_a_tour_takes_it_out(self):
        tour = self._tour()

        tour.active = False

        self.assertFalse(self._entry(tour))

    def test_the_entries_follow_the_catalogue_order(self):
        first = self._tour(name="A Tour", sequence=1)
        second = self._tour(name="B Tour", sequence=2)

        self.assertLess(
            self._entry(first).sequence, self._entry(second).sequence,
            "The menu is in a different order from the catalogue.",
        )

    def test_a_sync_that_changes_nothing_does_not_touch_the_row(self):
        """Every write to a tour triggers a rebuild, so a rebuild that rewrites
        unchanged rows would churn `write_date` on the whole menu all day."""
        tour = self._tour()
        entry = self._entry(tour)
        before = entry.write_date

        tour.price_per_person = 99.0
        entry.invalidate_recordset()

        self.assertEqual(entry.write_date, before)

    # --- The setting --------------------------------------------------------

    def test_switching_it_off_removes_what_it_made(self):
        tour = self._tour()
        self.assertTrue(self._entry(tour))

        self.env.company.tour_auto_menu = False

        self.assertFalse(self._entry(tour))
        self.assertFalse(self._root(), "The empty Tours heading was left behind.")
        self.assertFalse(self._kind("catalog"))

    def test_switching_it_back_on_rebuilds_the_menu(self):
        tour = self._tour()
        self.env.company.tour_auto_menu = False

        self.env.company.tour_auto_menu = True

        self.assertTrue(self._entry(tour))

    def test_it_is_on_by_default(self):
        """An operator who publishes a tour means for people to find it."""
        company = self.env["res.company"].create({"name": "Second Operator"})

        self.assertTrue(company.tour_auto_menu)

    def test_a_tour_made_while_it_is_off_does_not_appear(self):
        self.env.company.tour_auto_menu = False

        tour = self._tour()

        self.assertFalse(self._entry(tour))

    def test_a_hand_made_menu_entry_is_never_touched(self):
        """The whole reason entries are marked rather than matched by URL."""
        self._tour()
        mine = self.env["website.menu"].create({
            "name": "About Us",
            "url": "/about",
            "parent_id": self.website.menu_id.id,
            "website_id": self.website.id,
        })

        self.env.company.tour_auto_menu = False

        self.assertTrue(mine.exists(), "It deleted a menu entry it did not make.")
        self.assertEqual(mine.name, "About Us")
