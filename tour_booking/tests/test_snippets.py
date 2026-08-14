"""The booking blocks, drawn by a real browser.

These blocks are shells whose content arrives over RPC and whose calendar is
started by an interaction on markup that did not exist when the page loaded.
None of that is visible to a Python test: a block that fetches nothing, or
fetches and then fails to boot its calendar, renders as an empty band of page
and every server-side assertion still passes.

So each of these opens the page in headless Chrome and waits — the `ready`
expression is the test. Without one the assertion runs before anything has been
drawn and passes whatever happens next, which is exactly how a broken kanban
shipped twice.
"""

import json
import re

from odoo.tests import tagged
from odoo.tests.common import HttpCase, freeze_time

from .common import TourCase

# The calendar opens on the month the server says it is, so "is there a
# bookable date on screen" is only a stable question if the clock is stable.
# Frozen mid-month, with the fixture departure ten days later: no month
# boundary to fall over, and no run-at-23:59 flake.
TODAY = "2027-03-10 09:00:00"
DEPARTURE = "2027-03-20 08:00:00"

# Pasted verbatim into a page, which is what an operator's saved page holds:
# `data-` attributes and an empty div, because the editor saves the rendered
# DOM and anything server-rendered here would be frozen at drop time.
SNIPPETS = {
    "experiences": """
        <section class="s_tour_experiences s_tour_dynamic"
                 data-tour-widget="experiences" data-tour-columns="3">
            <div class="container"><div class="o_tour_snippet_content"/></div>
        </section>
    """,
    "book": """
        <section class="s_tour_book s_tour_dynamic"
                 data-tour-widget="book" data-tour-id="%(tour_id)s">
            <div class="container"><div class="o_tour_snippet_content"/></div>
        </section>
    """,
    "experience": """
        <section class="s_tour_experience s_tour_dynamic"
                 data-tour-widget="experience" data-tour-id="%(tour_id)s">
            <div class="container"><div class="o_tour_snippet_content"/></div>
        </section>
    """,
    "unset": """
        <section class="s_tour_experience s_tour_dynamic"
                 data-tour-widget="experience">
            <div class="container"><div class="o_tour_snippet_content"/></div>
        </section>
    """,
    "button": """
        <section class="s_tour_book_button s_tour_dynamic"
                 data-tour-widget="button" data-tour-columns="3">
            <div class="container">
                <button type="button" class="btn btn-primary o_tour_book_open">Book now</button>
                <div class="modal fade o_tour_book_modal" tabindex="-1" aria-hidden="true">
                    <div class="modal-dialog modal-xl">
                        <div class="modal-content">
                            <div class="modal-body o_tour_snippet_content"/>
                        </div>
                    </div>
                </div>
            </div>
        </section>
    """,
    # The external embed, exercised through the loader an operator pastes. Same
    # origin here — a test server is only ever one host — but the loader reads
    # its origin off its own script tag, so the code path is the one a real
    # site takes.
    "embed": """
        <script src="/tour/embed.js"></script>
        <div id="host" data-tour-widget="book" data-tour-id="%(tour_id)s"></div>
    """,
    "embed_button": """
        <script src="/tour/embed.js"></script>
        <div id="host" data-tour-widget="button" data-tour-label="Reserve"></div>
    """,
}


@tagged("post_install", "-at_install")
class TestSnippets(HttpCase, TourCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tour.is_published = True
        # Something bookable, or the calendar renders a month of dead cells and
        # the tests below cannot tell that from a calendar that never loaded.
        cls.departure = cls.env["tour.departure"].create({
            "tour_id": cls.tour.id,
            "date": DEPARTURE[:10],
            "start_datetime": DEPARTURE,
            "capacity": 10,
            "min_pax": 1,
            "max_pax": 6,
        })

    def _page(self, name):
        """A published page holding one block, and its URL.

        Created directly rather than dropped through the editor: what is being
        tested is whether the saved markup comes alive on a visitor's page,
        which is the thing that breaks, and driving the builder to get there
        would make every one of these a test of the builder instead.
        """
        arch = """
            <t name="Block" t-name="tour_booking.test_page_%(name)s">
                <t t-call="website.layout">
                    <div id="wrap" class="oe_structure">%(body)s</div>
                </t>
            </t>
        """ % {
            "name": name,
            "body": SNIPPETS[name] % {"tour_id": self.tour.id},
        }
        view = self.env["ir.ui.view"].create({
            "name": "Block %s" % name,
            "type": "qweb",
            "arch": arch,
            "key": "tour_booking.test_page_%s" % name,
        })
        self.env["website.page"].create({
            "view_id": view.id,
            "url": "/block-%s" % name,
            "is_published": True,
        })
        return "/block-%s" % name

    # --- The blocks ---------------------------------------------------------

    def test_the_experiences_block_fetches_its_cards(self):
        self.browser_js(
            self._page("experiences"),
            """
            const cards = document.querySelectorAll(".s_tour_experiences .o_tour_card");
            if (!cards.length) {
                throw new Error("The Experiences block drew no cards.");
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.s_tour_experiences .o_tour_card')",
            timeout=90,
        )

    @freeze_time(TODAY)
    def test_the_booking_box_block_boots_its_calendar(self):
        """The block fetches markup and an interaction has to start on markup
        that did not exist when the page loaded. If that wiring is wrong the
        card appears and the month never renders."""
        self.browser_js(
            self._page("book"),
            """
            const days = document.querySelectorAll(".s_tour_book .o_tour_day");
            if (!days.length) {
                throw new Error("The booking box drew no calendar.");
            }
            if (!document.querySelector(".s_tour_book .o_tour_day.available")) {
                throw new Error("The calendar rendered but offered no bookable date.");
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.s_tour_book .o_tour_day')",
            timeout=90,
        )

    @freeze_time(TODAY)
    def test_the_experience_block_draws_the_experience_and_the_calendar(self):
        self.browser_js(
            self._page("experience"),
            """
            if (!document.querySelector(".s_tour_experience .o_tour_widget")) {
                throw new Error("The Experience block drew no booking widget.");
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.s_tour_experience .o_tour_day')",
            timeout=90,
        )

    def test_a_block_with_no_experience_chosen_says_so(self):
        """What the operator sees the second after they drop it. An empty band
        of page tells them nothing about what to do next."""
        self.browser_js(
            self._page("unset"),
            """
            const hint = document.querySelector(".o_tour_snippet_empty");
            if (!hint || !hint.textContent.trim()) {
                throw new Error("An unconfigured block said nothing.");
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.o_tour_snippet_empty')",
            timeout=90,
        )

    def test_the_book_now_button_opens_the_catalogue(self):
        self.browser_js(
            self._page("button"),
            # Evaluated as a plain script, not a module, so there is no `await`
            # to be had. Bootstrap adds `show` behind a transition, so the check
            # waits in a timeout and reports through the console, which is what
            # browser_js listens to either way.
            """
            document.querySelector(".o_tour_book_open").click();
            setTimeout(() => {
                try {
                    const modal = document.querySelector(".o_tour_book_modal");
                    if (!modal.classList.contains("show")) {
                        throw new Error("Book now did not open the modal.");
                    }
                    if (!modal.querySelector(".o_tour_card")) {
                        throw new Error("The modal opened with no experiences in it.");
                    }
                    console.log('test successful');
                } catch (error) {
                    console.error(error.message);
                }
            }, 800);
            """,
            ready="!!document.querySelector('.o_tour_book_modal .o_tour_card')",
            timeout=90,
        )

    # --- The external embed -------------------------------------------------

    def test_the_loader_frames_the_widget_and_sizes_it_to_its_content(self):
        """An iframe cannot size itself across origins, so the page inside
        measures itself and posts the number up. Get this wrong and every
        embedded widget is a short box with its own scrollbar."""
        self.browser_js(
            self._page("embed"),
            """
            const frame = document.querySelector("#host iframe.tour-booking-frame");
            if (!frame) {
                throw new Error("The loader inserted no iframe.");
            }
            if (parseInt(frame.style.height, 10) <= 400) {
                throw new Error(
                    `The frame was never resized to its content (${frame.style.height}).`
                );
            }
            console.log('test successful');
            """,
            # 400px is the loader's starting height, so a frame still at 400 is
            # one that never heard back from the page inside it.
            ready="""
                (() => {
                    const f = document.querySelector('#host iframe.tour-booking-frame');
                    return !!f && parseInt(f.style.height, 10) > 400;
                })()
            """,
            timeout=90,
        )

    @freeze_time(TODAY)
    def test_book_now_inside_a_frame_leaves_the_frame(self):
        """The point of the whole design.

        A booking POSTed from inside a cross-origin frame is rejected: the
        session cookie is not sent there, so the CSRF token in that document was
        minted against a session that will not exist. Book now must therefore
        not submit — it must hand a first-party URL up to the host page.

        The frame is same-origin here only so the test can reach into it. The
        interception it is checking does not know or care about origins: it
        always fires.
        """
        self.browser_js(
            self._page("embed"),
            """
            const opened = [];
            window.open = (url) => { opened.push(url); return null; };
            const doc = document.querySelector("#host iframe").contentDocument;
            doc.querySelector(".o_tour_day.available").click();
            setTimeout(() => {
                try {
                    doc.querySelector(".o_tour_book_form").requestSubmit();
                    setTimeout(() => {
                        try {
                            if (opened.length !== 1) {
                                throw new Error(
                                    `Book now did not hand a URL to the host page (${opened.length}).`
                                );
                            }
                            const url = new URL(opened[0]);
                            if (url.origin !== window.location.origin) {
                                throw new Error(`Book now left the instance: ${url.origin}`);
                            }
                            if (!url.searchParams.get("departure_id")) {
                                throw new Error(`No departure carried over: ${opened[0]}`);
                            }
                            console.log('test successful');
                        } catch (error) {
                            console.error(error.message);
                        }
                    }, 400);
                } catch (error) {
                    console.error(error.message);
                }
            }, 300);
            """,
            ready="""
                (() => {
                    const f = document.querySelector('#host iframe');
                    const d = f && f.contentDocument;
                    return !!(d && d.querySelector('.o_tour_day.available'));
                })()
            """,
            timeout=90,
        )

    def test_the_loader_ignores_a_navigate_message_pointing_elsewhere(self):
        """The loader turns a message into `window.open`. If it took any URL it
        was handed, a widget on somebody's site would be a redirector: anything
        that can post a message to that page could send its visitors away.
        """
        self.browser_js(
            self._page("embed"),
            """
            const opened = [];
            window.open = (url) => { opened.push(url); return null; };
            window.postMessage(
                { tour_booking: "navigate", url: "https://evil.example/steal" }, "*"
            );
            setTimeout(() => {
                try {
                    if (opened.length) {
                        throw new Error(`The loader opened a foreign URL: ${opened[0]}`);
                    }
                    console.log('test successful');
                } catch (error) {
                    console.error(error.message);
                }
            }, 500);
            """,
            ready="!!document.querySelector('#host iframe.tour-booking-frame')",
            timeout=90,
        )

    def test_the_loader_mounts_each_placeholder_once(self):
        """It runs on pages it does not control, some of which load it twice or
        re-run scripts after a client-side navigation. Two iframes stacked in
        one slot is the visible symptom."""
        self.browser_js(
            self._page("embed"),
            """
            const script = document.createElement("script");
            script.src = "/tour/embed.js";
            document.body.appendChild(script);
            setTimeout(() => {
                try {
                    const frames = document.querySelectorAll("#host iframe");
                    if (frames.length !== 1) {
                        throw new Error(`The slot holds ${frames.length} frames.`);
                    }
                    console.log('test successful');
                } catch (error) {
                    console.error(error.message);
                }
            }, 1000);
            """,
            ready="!!document.querySelector('#host iframe.tour-booking-frame')",
            timeout=90,
        )

    def test_the_book_now_button_widget_opens_and_closes_an_overlay(self):
        """The button is the one widget the loader draws itself rather than
        framing, so its overlay has nothing behind it but this code."""
        self.browser_js(
            self._page("embed_button"),
            """
            const button = document.querySelector("#host button.tour-booking-button");
            if (button.textContent.trim() !== "Reserve") {
                throw new Error(`The label was ignored: ${button.textContent}`);
            }
            button.click();
            setTimeout(() => {
                try {
                    const overlay = document.querySelector(".tour-booking-overlay");
                    if (!overlay) {
                        throw new Error("The button opened no overlay.");
                    }
                    if (!overlay.querySelector("iframe.tour-booking-frame")) {
                        throw new Error("The overlay framed nothing.");
                    }
                    document.dispatchEvent(
                        new KeyboardEvent("keydown", { key: "Escape" })
                    );
                    setTimeout(() => {
                        try {
                            if (document.querySelector(".tour-booking-overlay")) {
                                throw new Error("Escape did not close the overlay.");
                            }
                            console.log('test successful');
                        } catch (error) {
                            console.error(error.message);
                        }
                    }, 300);
                } catch (error) {
                    console.error(error.message);
                }
            }, 800);
            """,
            ready="!!document.querySelector('#host button.tour-booking-button')",
            timeout=90,
        )

    def test_the_block_options_reach_the_website_editor(self):
        """The option panel is the only way to choose which experience a block
        shows, and it lives in an editor-only bundle that no other test loads.
        A typo in that file is invisible until an operator drops a block and
        finds nothing on the right-hand side.
        """
        self.browser_js(
            "/odoo/action-website.website_preview",
            """
            const { registry } = odoo.loader.modules.get("@web/core/registry");
            if (!registry.category("website-plugins").contains("tourSnippetOption")) {
                throw new Error("The booking block options never registered.");
            }
            console.log('test successful');
            """,
            ready="""
                !!(odoo.loader.modules.get('@web/core/registry')
                   && odoo.loader.modules.get('@web/core/registry')
                        .registry.category('website-plugins')
                        .contains('tourSnippetOption'))
            """,
            login="admin",
            timeout=120,
        )

    def test_the_booking_blocks_are_offered_in_the_block_picker(self):
        """What the editor's Blocks panel is actually handed.

        The obvious checks are both worthless here and I made them both: our
        own inheriting view's arch says nothing about whether the inheritance
        applied, and the option plugin registering says nothing about whether
        the blocks are listed. This renders the panel the way the builder does
        and looks for the entries in it.
        """
        panel = self._snippet_panel()

        for name in ["Experiences", "Experience", "Booking Box", "Book Now Button"]:
            self.assertIn(
                '<div name="%s" data-oe-type="snippet"' % name, panel,
                "%s is not offered as a block." % name,
            )
        self.assertEqual(panel.count('data-oe-snippet-key="s_tour_book"'), 1)

    def test_the_blocks_have_a_category_of_their_own_listed_first(self):
        """They were in Catalog, under everything e-commerce contributes, and
        were simply not findable. Catalog also already means "the things you
        sell" on a site with a shop."""
        panel = self._snippet_panel()

        ours = panel.find('data-o-snippet-group="tour_widgets"')
        self.assertNotEqual(ours, -1, "There is no Tour Widgets category.")
        for other in ("intro", "columns", "catalog"):
            position = panel.find('data-o-snippet-group="%s"' % other)
            self.assertLess(ours, position, "%s comes before Tour Widgets." % other)

    def test_every_block_is_filed_under_tour_widgets(self):
        panel = self._snippet_panel()

        for key in ("s_tour_experiences", "s_tour_experience",
                    "s_tour_book", "s_tour_book_button"):
            entry = re.search(
                r'<div[^>]*data-oe-snippet-key="%s"[^>]*>' % key, panel
            )
            self.assertIsNotNone(entry, "%s is not offered at all." % key)
            self.assertIn('data-o-group="tour_widgets"', entry.group(0), key)

    def test_the_fetched_blocks_preview_as_a_picture(self):
        """The gallery previews a block by rendering it, and these render as an
        empty shell until their content is fetched. Without a picture an
        operator is choosing between white rectangles."""
        panel = self._snippet_panel()

        for key in ("s_tour_experiences", "s_tour_experience", "s_tour_book"):
            entry = re.search(
                r'<div[^>]*data-oe-snippet-key="%s"[^>]*>' % key, panel
            )
            self.assertIn(
                'data-o-image-preview="/tour_booking/static/src/img/snippets_previews/',
                entry.group(0), key,
            )

    def _snippet_panel(self):
        """The Blocks panel markup, fetched as the builder fetches it.

        Through the web client rather than by calling the model directly: the
        templates read `request`, which does not exist in a test's own thread.
        """
        self.authenticate("admin", "admin")
        response = self.url_open("/web/dataset/call_kw", data=json.dumps({
            "jsonrpc": "2.0", "method": "call",
            "params": {
                "model": "ir.ui.view", "method": "render_public_asset",
                "args": ["website.snippets", {}], "kwargs": {},
            },
        }), headers={"Content-Type": "application/json"})
        return response.json()["result"]

    def test_a_block_draws_its_content_inside_the_editor(self):
        """The gap that let a white band ship.

        An interaction registered only in `public.interactions` does not run
        while editing, so these blocks drew nothing until the page was saved.
        Every test above loads the page as a visitor, where it worked
        perfectly — which is exactly why none of them noticed.
        """
        path = self._page("book")
        self.browser_js(
            "/odoo/action-website.website_preview?path=%s&enable_editor=1" % path,
            """
            // The editor draws two iframes; the one holding the page being
            // edited is not the fallback, so it is found by its content.
            const frame = [...document.querySelectorAll("iframe")].find(
                (f) => f.contentDocument && f.contentDocument.querySelector(".s_tour_book"));
            const block = frame.contentDocument.querySelector(".s_tour_book");
            if (!block.querySelector(".o_tour_widget")) {
                throw new Error("The block drew nothing in the editor.");
            }
            if (!block.querySelector(".o_tour_day")) {
                throw new Error("The block drew a card around an empty calendar.");
            }
            console.log('test successful');
            """,
            ready="""
                (() => {
                    const f = [...document.querySelectorAll('iframe')].find(
                        (x) => x.contentDocument
                            && x.contentDocument.querySelector('.s_tour_book .o_tour_day'));
                    return !!f;
                })()
            """,
            login="admin",
            timeout=120,
        )
