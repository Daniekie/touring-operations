"""Does the back office actually render?

The Python suite draws nothing. It happily stayed green while the Tours kanban
threw on every load, because a kanban card is a JS template and no test here
touches one. These tests drive a real headless browser instead, so a view that
crashes on render fails the build rather than the operator.

They are deliberately shallow — open the screen, confirm the thing that proves
it rendered — because their job is catching the crash, not the layout.
"""

from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install")
class TestBackendUI(HttpCase):

    def test_the_tours_kanban_renders(self):
        """The exact bug this file exists for: a card that throws on render.

        The `ready` gate is the whole test. Without one the code runs the
        instant the page loads, before the view has drawn anything, and passes
        whatever happens next — which is how a broken kanban shipped twice.
        """
        self.browser_js(
            "/odoo/action-tour_booking.tour_tour_action",
            """
            if (!document.querySelector(".o_kanban_record")) {
                throw new Error("The Experiences kanban drew no cards.");
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.o_kanban_record')",
            login="admin",
            timeout=90,
        )

    def test_the_booking_calendar_renders(self):
        self.browser_js(
            "/odoo/action-tour_booking.action_booking_calendar",
            """
            if (!document.querySelector(".o_tour_grid_table")) {
                throw new Error("The Booking Calendar rendered no grid.");
            }
            console.log('test successful');
            """,
            # The component fetches its week before it can draw anything, so the
            # assertion has to wait for the result rather than race it.
            # A boolean, not the element: the ready expression crosses the
            # devtools bridge, and a DOM node does not survive that as truthy.
            ready="!!document.querySelector('.o_tour_grid_table')",
            login="admin",
            timeout=90,
        )

    def test_the_passenger_list_renders(self):
        self.browser_js(
            "/odoo/action-tour_booking.tour_passenger_action",
            "console.log('test successful')",
            ready="!!document.querySelector('.o_list_view')",
            login="admin",
            timeout=90,
        )

    def test_placing_a_booking_opens_a_usable_form(self):
        """The menu entry drops straight onto a new booking form, so a broken
        default or a missing field shows up here rather than at the counter."""
        self.browser_js(
            "/odoo/action-tour_booking.tour_booking_new_action",
            """
            if (!document.querySelector(".o_form_view")) {
                throw new Error("Place a Booking did not open a form.");
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.o_form_view')",
            login="admin",
            timeout=90,
        )

    def test_creating_an_experience_opens_a_usable_form(self):
        """A new experience is one page, not a stub you save and come back to.

        The form used to hide everything behind `invisible="not id"`, so the
        assertions below are the ones that would have caught that: the whole
        thing is on screen before the record exists, in two rows of tabs, with a
        button that says what finishing looks like.
        """
        self.browser_js(
            "/odoo/action-tour_booking.tour_tour_new_action",
            """
            if (!document.querySelector(".o_form_view")) {
                throw new Error("New Experience did not open a form.");
            }
            if (!document.querySelector('button[name="action_confirm"]')) {
                throw new Error("The new form has no Confirm button.");
            }
            const rows = document.querySelectorAll(".o_form_sheet .o_notebook");
            if (rows.length !== 2) {
                throw new Error(`Expected two rows of tabs, drew ${rows.length}.`);
            }
            // Order matters and is the thing that went wrong once: an
            // "Optional Settings" group sat above the row headed "Required".
            // Required is the first row, everything optional is in the second.
            const labels = (row) =>
                [...row.querySelectorAll(".nav-link")].map((el) => el.textContent.trim());
            const [required, optional] = rows;
            for (const tab of ["Description", "Start Times", "Availability"]) {
                if (!labels(required).includes(tab)) {
                    throw new Error(`"${tab}" is not in the first row: ${labels(required)}`);
                }
            }
            for (const tab of ["Settings", "Images"]) {
                if (!labels(optional).includes(tab)) {
                    throw new Error(`"${tab}" is not in the second row: ${labels(optional)}`);
                }
            }
            // Only what somebody actually has to decide belongs above the
            // tabs. Everything with a working default drifts back up there one
            // field at a time unless something says otherwise.
            const sheet = document.querySelector(".o_form_sheet");
            const above = [...sheet.querySelectorAll("[name]")]
                .filter((el) =>
                    required.compareDocumentPosition(el) &
                    Node.DOCUMENT_POSITION_PRECEDING)
                .map((el) => el.getAttribute("name"));
            for (const field of ["duration_hours", "default_capacity", "price_per_person"]) {
                if (!above.includes(field)) {
                    throw new Error(`${field} should be above the tabs: ${above}`);
                }
            }
            for (const field of ["location_id", "has_specific_time",
                                 "booking_cutoff_hours", "cancellation_policy_id"]) {
                if (above.includes(field)) {
                    throw new Error(`${field} has a default and belongs under Optional.`);
                }
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.o_form_view .o_notebook')",
            login="admin",
            timeout=90,
        )

    def test_editing_an_experience_shows_the_publish_control(self):
        """Putting a tour on sale is the one decision on that form, so it uses
        Odoo's own publish control rather than a checkbox.

        A saved record, because the control is hidden until there is something
        to publish — which means the new-experience test above never renders it,
        and a wrong widget name would crash only for an operator opening a tour
        they already had.
        """
        tour = self.env["tour.tour"].create({
            "name": "Publishable",
            "duration_hours": 2.0,
            "default_capacity": 8,
            "price_per_person": 30.0,
            "has_specific_time": False,
        })
        self.browser_js(
            "/odoo/action-tour_booking.tour_tour_action/%s" % tour.id,
            """
            if (!document.querySelector(".o_form_view .o_menu_systray, .o_form_view")) {
                throw new Error("The experience form did not open.");
            }
            if (!document.querySelector('[name="is_published"]')) {
                throw new Error("The publish control did not render.");
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.o_form_view [name=\"is_published\"]')",
            login="admin",
            timeout=90,
        )

    def test_the_bookings_list_renders(self):
        self.browser_js(
            "/odoo/action-tour_booking.tour_booking_action",
            "console.log('test successful')",
            ready="!!document.querySelector('.o_list_view')",
            login="admin",
            timeout=90,
        )

    def test_the_put_on_a_website_wizard_opens_with_a_picture(self):
        """It is a dialog nothing else opens, and it draws a Binary field read
        off disk — two things that fail quietly and only for the operator."""
        self.browser_js(
            "/odoo/action-tour_booking.tour_embed_action",
            """
            const dialog = document.querySelector(".modal .o_form_view");
            if (!dialog) {
                throw new Error("The wizard did not open.");
            }
            if (!dialog.querySelector('[name="preview_image"] img')) {
                throw new Error("No picture of the chosen widget.");
            }
            if (!dialog.querySelector('[name="code"]')) {
                throw new Error("No code to paste.");
            }
            const steps = [...dialog.querySelectorAll(".o_tour_embed_step")]
                .map((el) => el.textContent.trim());
            if (steps.length !== 2) {
                throw new Error(`Expected two steps, found ${steps.length}.`);
            }
            console.log('test successful');
            """,
            ready="!!document.querySelector('.modal [name=\"preview_image\"] img')",
            login="admin",
            timeout=90,
        )
