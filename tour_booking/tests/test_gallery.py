"""The photo mosaic and its lightbox.

Worth testing in a browser rather than only in Python: the mosaic is markup,
but every part an operator would complain about — clicking a photo, paging
through them, getting out again — happens in JavaScript over elements that are
hidden until it runs.
"""

import base64

from odoo.tests import tagged
from odoo.tests.common import HttpCase, freeze_time

from .common import TourCase

# A 1x1 GIF. These tests are about how many photos there are and what happens
# when one is clicked, never about what is in them.
IMAGE = base64.b64encode(base64.b64decode(
    "R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="
))


@tagged("post_install", "-at_install")
class TestGallery(HttpCase, TourCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tour.write({"is_published": True, "image_1920": IMAGE})
        # Six, so there is an overflow past the four the mosaic shows.
        for index in range(6):
            cls.env["tour.tour.image"].create({
                "tour_id": cls.tour.id,
                "name": "Photo %s" % index,
                "sequence": index * 10,
                "image_1920": IMAGE,
            })

    # --- The markup ---------------------------------------------------------

    def test_every_photo_is_in_the_page_even_the_ones_not_shown(self):
        """The lightbox pages through all of them without a second request,
        which is only true if they are all here to begin with."""
        body = self.url_open(self.tour.website_url).text

        self.assertEqual(body.count('class="o_tour_photo"'), 4)
        self.assertEqual(body.count('class="o_tour_photo d-none"'), 2)
        self.assertEqual(body.count('class="o_tour_photo o_tour_photo_main"'), 1)

    def test_the_photos_come_before_the_line_of_facts(self):
        """The mosaic is what the page is selling. A row of grey pills between
        the title and the pictures pushed them down for no gain."""
        body = self.url_open(self.tour.website_url).text

        self.assertLess(
            body.index("o_tour_photos"), body.index("o_tour_meta"),
            "The duration/price line is back above the photos.",
        )

    def test_the_main_picture_leads_the_mosaic(self):
        body = self.url_open(self.tour.website_url).text

        self.assertIn('class="o_tour_photo o_tour_photo_main" data-index="0"', body)

    def test_a_show_all_button_appears_only_when_photos_are_hidden(self):
        with_overflow = self.url_open(self.tour.website_url).text
        self.assertIn("o_tour_photos_all", with_overflow)

        self.tour.image_ids[4:].unlink()
        without = self.url_open(self.tour.website_url).text
        self.assertNotIn("o_tour_photos_all", without)

    def test_a_tour_with_no_photos_at_all_draws_no_mosaic(self):
        """An empty grid with a border round it is worse than nothing."""
        bare = self.env["tour.tour"].create({
            "name": "No Photos", "duration_hours": 1.0, "default_capacity": 4,
            "price_per_person": 5.0, "is_published": True,
            "has_specific_time": False,
        })

        body = self.url_open(bare.website_url).text

        self.assertNotIn("o_tour_photos", body)

    def test_a_visitor_can_actually_fetch_the_photos(self):
        """The bug this exists for, and the reason it survived so long.

        Every earlier test counted `<img>` tags, which were always there. The
        gallery photos live on their own model, `/web/image/` checks access as
        the visitor, and `tour.tour.image` had no public rule — so every one of
        them was a broken-image placeholder on a page that otherwise looked
        finished.
        """
        photo = self.tour.image_ids[0]

        response = self.url_open(
            "/web/image/tour.tour.image/%s/image_1920" % photo.id
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["Content-Type"].startswith("image/"))
        self.assertNotIn("placeholder", response.headers.get("Content-Disposition", ""))

    def test_a_photo_of_an_unpublished_tour_is_not_public(self):
        """The rule that makes the access above safe."""
        hidden = self.env["tour.tour"].create({
            "name": "Hidden", "duration_hours": 1.0, "default_capacity": 4,
            "price_per_person": 5.0, "is_published": False,
            "has_specific_time": False,
        })
        photo = self.env["tour.tour.image"].create({
            "tour_id": hidden.id, "name": "Secret", "image_1920": IMAGE,
        })

        response = self.url_open(
            "/web/image/tour.tour.image/%s/image_1920" % photo.id
        )

        self.assertIn(
            "placeholder", response.headers.get("Content-Disposition", "placeholder"),
            "An unpublished tour's photo was served to the public.",
        )

    # --- The lightbox -------------------------------------------------------

    def test_clicking_a_photo_enlarges_it_and_pages_through_the_rest(self):
        self.browser_js(
            self.tour.website_url,
            """
            document.querySelector(".o_tour_photo_main").click();
            setTimeout(() => {
                try {
                    const box = document.querySelector(".o_tour_lightbox");
                    if (!box || box.classList.contains("d-none")) {
                        throw new Error("Clicking a photo enlarged nothing.");
                    }
                    const count = () =>
                        box.querySelector(".o_tour_lightbox_count").textContent.trim();
                    if (count() !== "1 / 7") {
                        throw new Error(`Opened on the wrong photo: ${count()}`);
                    }
                    box.querySelector(".o_tour_lightbox_next").click();
                    if (count() !== "2 / 7") {
                        throw new Error(`Next did not advance: ${count()}`);
                    }
                    box.querySelector(".o_tour_lightbox_prev").click();
                    box.querySelector(".o_tour_lightbox_prev").click();
                    if (count() !== "7 / 7") {
                        throw new Error(`Previous did not wrap around: ${count()}`);
                    }
                    document.dispatchEvent(
                        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
                    if (!box.classList.contains("d-none")) {
                        throw new Error("Escape did not close it.");
                    }
                    console.log('test successful');
                } catch (error) {
                    console.error(error.message);
                }
            }, 400);
            """,
            ready="!!document.querySelector('.o_tour_photos_ready')",
            timeout=90,
        )

    def test_show_all_photos_opens_on_the_first_one(self):
        self.browser_js(
            self.tour.website_url,
            """
            document.querySelector(".o_tour_photos_all").click();
            setTimeout(() => {
                try {
                    const box = document.querySelector(".o_tour_lightbox");
                    if (box.classList.contains("d-none")) {
                        throw new Error("Show all photos opened nothing.");
                    }
                    const shown = box.querySelector(".o_tour_lightbox_count").textContent.trim();
                    if (shown !== "1 / 7") {
                        throw new Error(`Opened at ${shown}.`);
                    }
                    console.log('test successful');
                } catch (error) {
                    console.error(error.message);
                }
            }, 400);
            """,
            ready="!!document.querySelector('.o_tour_photos_ready')",
            timeout=90,
        )

    def test_clicking_the_photograph_itself_does_not_close_the_lightbox(self):
        """Otherwise every attempt to look closely shuts the thing."""
        self.browser_js(
            self.tour.website_url,
            """
            document.querySelector(".o_tour_photo_main").click();
            setTimeout(() => {
                try {
                    const box = document.querySelector(".o_tour_lightbox");
                    box.querySelector(".o_tour_lightbox_stage img").click();
                    if (box.classList.contains("d-none")) {
                        throw new Error("Clicking the photo closed the lightbox.");
                    }
                    box.click();
                    if (!box.classList.contains("d-none")) {
                        throw new Error("Clicking the backdrop did not close it.");
                    }
                    console.log('test successful');
                } catch (error) {
                    console.error(error.message);
                }
            }, 400);
            """,
            ready="!!document.querySelector('.o_tour_photos_ready')",
            timeout=90,
        )


@tagged("post_install", "-at_install")
class TestBookingWidgetPrice(HttpCase, TourCase):
    """Where the price is shown, and what it says once a party size is chosen."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tour.is_published = True
        cls.departure = cls.env["tour.departure"].create({
            "tour_id": cls.tour.id,
            "date": "2027-03-20",
            "start_datetime": "2027-03-20 08:00:00",
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        })

    def test_the_price_is_in_the_line_under_the_title(self):
        """It used to head the booking card, which is sticky — so it slid under
        the site header and was the one thing on the page you could not read."""
        body = self.url_open(self.tour.website_url).text

        self.assertIn("o_tour_meta_price", body)

    def test_the_total_is_hidden_until_a_departure_is_chosen(self):
        """Before a date there is no party size to multiply, and one person's
        fare labelled Total is a wrong answer stated confidently."""
        body = self.url_open(self.tour.website_url).text

        self.assertIn("o_tour_total d-none", body)

    @freeze_time("2027-03-10 09:00:00")
    def test_the_total_follows_the_party_size(self):
        self.browser_js(
            self.tour.website_url,
            """
            document.querySelector(".o_tour_day.available").click();
            setTimeout(() => {
                try {
                    const total = document.querySelector(".o_tour_total");
                    if (total.classList.contains("d-none")) {
                        throw new Error("Choosing a date showed no total.");
                    }
                    const value = () =>
                        document.querySelector(".o_tour_total_value").textContent;
                    if (!value().includes("50")) {
                        throw new Error(`One seat should be 50, got ${value()}`);
                    }
                    const pax = document.querySelector(".o_tour_pax");
                    pax.value = 3;
                    pax.dispatchEvent(new Event("change"));
                    if (!value().includes("150")) {
                        throw new Error(`Three seats should be 150, got ${value()}`);
                    }
                    if (!document.querySelector(".o_tour_total_label")
                             .textContent.includes("3")) {
                        throw new Error("The total does not say what it is made of.");
                    }
                    console.log('test successful');
                } catch (error) {
                    console.error(error.message);
                }
            }, 500);
            """,
            ready="!!document.querySelector('.o_tour_day.available')",
            timeout=90,
        )

    def test_the_sticky_card_clears_the_site_header(self):
        """It follows the page down, and every theme puts a header across the
        top of the viewport. Stuck to `top: 0` the card slides under it and
        the first thing on the card is cut in half."""
        self.browser_js(
            self.tour.website_url,
            """
            const card = document.querySelector(".o_tour_sticky");
            const header = document.querySelector("header#top");
            const offset = parseFloat(getComputedStyle(card).top);
            const height = header ? header.getBoundingClientRect().height : 0;
            if (getComputedStyle(card).position !== "sticky") {
                throw new Error("The booking card does not follow the page.");
            }
            if (!(offset > height)) {
                throw new Error(
                    `The card sticks at ${offset}px, under a ${height}px header.`);
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.o_tour_sticky')",
            timeout=90,
        )
