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
        """The exact bug this file exists for: a card reaching through
        `record.` for a field the view never declared."""
        self.browser_js(
            "/odoo/action-tour_booking.tour_tour_action",
            "console.log('test successful')",
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

    def test_the_bookings_list_renders(self):
        self.browser_js(
            "/odoo/action-tour_booking.tour_booking_action",
            "console.log('test successful')",
            login="admin",
            timeout=90,
        )
