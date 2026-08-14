import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

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

        Nothing in here may raise. By the time it runs the money has been taken,
        and an exception would roll back everything the callback did, leave the
        guest paid and unconfirmed with no record of why, and hand the provider
        an error it will retry until it gives up. One booking at a time, so that
        a departure cancelled under one guest cannot cost the others on the same
        callback their confirmation either.
        """
        super()._post_process()
        for transaction in self.filtered(lambda tx: tx.state == "done"):
            bookings = transaction.tour_booking_ids.filtered(
                lambda b: b.state == "draft"
            )
            for booking in bookings:
                transaction._confirm_booking(booking)

    def _confirm_booking(self, booking):
        """Confirm one paid booking, or say why it could not be.

        A failure here is a guest who has paid for a seat they cannot have —
        their departure was cancelled while they were at the provider, or it
        left. That is an operator's problem to settle, so it is written where an
        operator will find it: on the booking, and in the log.
        """
        self.ensure_one()
        try:
            # The savepoint is what keeps the rest of the callback usable: it
            # rolls back on the way out of the block, so a half-applied
            # confirmation cannot poison the transaction the message below and
            # every other booking on this callback still need.
            with self.env.cr.savepoint():
                booking.action_confirm()
        except UserError as error:
            reason = error.args[0] if error.args else ""
            _logger.error(
                "Booking %s was paid by transaction %s but could not be "
                "confirmed: %s",
                booking.name, self.reference, reason,
            )
            booking.message_post(body=_(
                "Payment %(reference)s went through, but this booking could "
                "not be confirmed: %(reason)s It is still unconfirmed and the "
                "guest has paid — settle or refund it by hand.",
                reference=self.reference,
                reason=reason,
            ))
            return False

        # After confirming, and only for the bookings this callback actually
        # confirmed: what was charged is recorded once, by the callback that
        # charged it. A retried webhook finds them confirmed and does not write
        # the figure a second time.
        booking._record_charged_amount(self)
        return True
