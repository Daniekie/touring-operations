import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    # The other side of `tour.booking.transaction_ids`. Declared explicitly
    # rather than left implicit so the relation table and its columns are named
    # once, in a form both models agree on.
    tour_booking_ids = fields.Many2many(
        "tour.booking",
        "tour_booking_transaction_rel",
        "transaction_id",
        "booking_id",
        string="Tour Bookings",
    )

    def _post_process(self):
        """Confirm the bookings whose payment went through.

        Idempotent on purpose. Providers retry webhooks, and a guest who
        refreshes the return page produces a second callback of their own; a
        repeated confirmation must be a no-op rather than a second seat taken or
        a second confirmation mail. `action_confirm` already skips bookings that
        are confirmed, so the guard here is about not touching cancelled ones.
        """
        super()._post_process()
        for transaction in self.filtered(lambda tx: tx.state == "done"):
            bookings = transaction.tour_booking_ids.filtered(
                lambda b: b.state == "draft"
            )
            if bookings:
                bookings.action_confirm()
