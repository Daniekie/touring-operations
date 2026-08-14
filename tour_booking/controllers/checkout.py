"""From a chosen departure to a paid booking.

The shape of the flow matters more than any single route in it. The booking is
created as a **draft before** the guest is sent to the payment provider, and
confirmed **after** the provider says the money arrived. That ordering is what
stops two guests paying for the same last seat: the draft holds the seats for
the duration of the redirect, and `tour.booking._cron_release_abandoned_drafts`
puts them back if the guest never returns.
"""

from odoo import _, fields, http
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.fields import Command
from odoo.http import request
from odoo.tools import consteq

from odoo.addons.payment.controllers import portal as payment_portal


class TourBookingCheckout(payment_portal.PaymentPortal):

    # --- Creating the booking ----------------------------------------------

    @http.route(["/tour/book"], type="http", auth="public", website=True, methods=["POST"])
    def book(self, departure_id=None, pax=1, **kwargs):
        """Take the widget's choice and open a draft booking.

        Everything here is re-derived server-side. The form carries a departure
        and a party size and nothing else that matters — no price, no capacity
        claim — because a value that arrives from a browser is a request, not a
        fact.
        """
        departure = request.env["tour.departure"].sudo().browse(
            int(departure_id or 0)
        ).exists()
        if not departure or not departure.tour_id.is_published:
            return request.not_found()

        try:
            pax = max(1, int(pax))
        except (TypeError, ValueError):
            pax = 1

        partner = request.env.user.partner_id
        if request.env.user._is_public():
            # A public visitor has no partner of their own yet. One is made at
            # the contact-details step; until then the booking hangs off the
            # website's public partner so the seats can be held immediately.
            partner = request.website.user_id.sudo().partner_id

        try:
            booking = request.env["tour.booking"].sudo().create({
                "departure_id": departure.id,
                "partner_id": partner.id,
                "pax": pax,
            })
        except (UserError, ValidationError) as error:
            return request.render("tour_booking.booking_refused", {
                "tour": departure.tour_id,
                "reason": error.args[0] if error.args else None,
            })

        return request.redirect(booking._checkout_url())

    # --- The checkout page -------------------------------------------------

    def _booking_from_token(self, booking_id, access_token):
        """The booking behind an access token, or an AccessError.

        The token is the only credential a guest has: the flow starts before
        anybody logs in, so the booking cannot be found by user.
        """
        booking_sudo = request.env["tour.booking"].sudo().browse(booking_id).exists()
        if not booking_sudo:
            raise MissingError(_("This booking no longer exists."))
        # A booking that has never been given a token stores False, and
        # `consteq` takes two strings — so the empty case is answered here
        # rather than letting it raise a TypeError and serve a 500 to somebody
        # who merely mistyped a URL.
        stored = booking_sudo.access_token or ""
        if not access_token or not consteq(stored, access_token):
            raise AccessError(_("The access token is invalid."))
        return booking_sudo

    @http.route(
        ["/tour/booking/<int:booking_id>"],
        type="http", auth="public", website=True,
    )
    def checkout(self, booking_id, access_token=None, **kwargs):
        """Contact details, extras, questions — and payment once it is a draft
        no longer."""
        try:
            booking_sudo = self._booking_from_token(booking_id, access_token)
        except (AccessError, MissingError):
            return request.redirect("/tours")

        values = {
            "booking": booking_sudo,
            "tour": booking_sudo.tour_id,
            "extras": booking_sudo.tour_id.extra_ids,
            "questions": booking_sudo.tour_id.question_ids,
            "refund_preview": booking_sudo._refund_preview(),
            "error": kwargs.get("error"),
        }
        if booking_sudo.state == "draft":
            values.update(self._prepare_payment_values(booking_sudo))
            return request.render("tour_booking.checkout", values)
        return request.render("tour_booking.booking_confirmation", values)

    def _prepare_payment_values(self, booking_sudo):
        """Everything `payment.form` needs to render itself.

        In the settlement currency, because that is what the transaction will be
        raised in: a provider offered here for a dollar amount and then handed a
        euro one is a provider that may not accept euros at all.
        """
        amount, currency = booking_sudo.payment_amount()
        # The report is filled in by the two calls below and read by
        # `payment.form` to tell a logged-in administrator *why* a provider they
        # expected to see is missing. A guest never sees it.
        availability_report = {}
        providers_sudo = request.env["payment.provider"].sudo()._get_compatible_providers(
            booking_sudo.company_id.id,
            booking_sudo.partner_id.id,
            amount,
            currency_id=currency.id,
            report=availability_report,
        )
        payment_methods_sudo = request.env["payment.method"].sudo()._get_compatible_payment_methods(
            providers_sudo.ids,
            booking_sudo.partner_id.id,
            currency_id=currency.id,
            report=availability_report,
        )
        return {
            "amount": amount,
            "currency": currency,
            "partner_id": booking_sudo.partner_id.id,
            "providers_sudo": providers_sudo,
            "payment_methods_sudo": payment_methods_sudo,
            "tokens_sudo": request.env["payment.token"].sudo(),
            "availability_report": availability_report,
            "transaction_route": "/tour/booking/%s/transaction" % booking_sudo.id,
            "landing_route": booking_sudo._checkout_url(),
            "access_token": booking_sudo.access_token,
            # One entry per compatible provider, keyed by id: the template
            # indexes this mapping directly, so a provider missing from it is a
            # KeyError rather than a hidden checkbox.
            "show_tokenize_input_mapping": self._compute_show_tokenize_input_mapping(
                providers_sudo
            ),
        }

    @http.route(
        ["/tour/booking/<int:booking_id>/details"],
        type="http", auth="public", website=True, methods=["POST"],
    )
    def details(self, booking_id, access_token=None, **post):
        """Save the guest's details, extras and answers.

        Prices are never read from the form. An extra contributes what the
        `tour.extra` record says it contributes, and the total is recomputed
        from the booking.
        """
        try:
            booking_sudo = self._booking_from_token(booking_id, access_token)
        except (AccessError, MissingError):
            return request.redirect("/tours")
        if booking_sudo.state != "draft":
            return request.redirect(booking_sudo._checkout_url())

        self._save_partner(booking_sudo, post)
        self._save_extras(booking_sudo, post)
        self._save_answers(booking_sudo, post)
        return request.redirect(booking_sudo._checkout_url())

    def _save_partner(self, booking_sudo, post):
        name = (post.get("name") or "").strip()
        email = (post.get("email") or "").strip()
        if not name and not email:
            return
        partner = booking_sudo.partner_id
        is_public = partner == request.website.user_id.sudo().partner_id
        values = {"name": name or partner.name, "email": email or partner.email,
                  "phone": (post.get("phone") or "").strip() or partner.phone}
        if is_public:
            # Never write onto the shared public partner: it is one record for
            # every anonymous visitor on the site.
            booking_sudo.partner_id = request.env["res.partner"].sudo().create(values)
        else:
            partner.sudo().write(values)

    def _save_extras(self, booking_sudo, post):
        booking_sudo.extra_line_ids.unlink()
        for extra in booking_sudo.tour_id.extra_ids:
            try:
                quantity = int(post.get("extra_%s" % extra.id) or 0)
            except ValueError:
                quantity = 0
            if quantity > 0:
                request.env["tour.booking.extra"].sudo().create({
                    "booking_id": booking_sudo.id,
                    "extra_id": extra.id,
                    "quantity": quantity,
                })

    @http.route(
        ["/tour/booking/<int:booking_id>/extras"],
        type="jsonrpc", auth="public", website=True,
    )
    def extras(self, booking_id, access_token=None, **post):
        """Re-price the booking against the extras chosen so far.
        -> {"html": the summary card}

        The quantities are **saved**, not merely quoted. A guest who ticks a
        wetsuit and goes straight to the payment buttons without pressing Save
        details would otherwise be charged for a booking that no longer matches
        the total they are reading — and the total is the thing they remember.

        Prices still come from `tour.extra` by way of `_save_extras`, and the
        summary is the same template the page was rendered with, so a number
        cannot be computed one way here and another way on reload.
        """
        booking_sudo = self._booking_from_token(booking_id, access_token)
        if booking_sudo.state == "draft":
            self._save_extras(booking_sudo, post)
        return {
            "html": request.env["ir.qweb"]._render(
                "tour_booking.booking_summary",
                {"booking": booking_sudo, "request": request},
            ),
        }

    def _save_answers(self, booking_sudo, post):
        booking_sudo.answer_ids.unlink()
        for question in booking_sudo.tour_id.question_ids:
            indexes = range(1, booking_sudo.pax + 1) if question.scope == "per_person" else [0]
            for index in indexes:
                key = "question_%s_%s" % (question.id, index)
                raw = post.get(key)
                if question.field_type == "bool":
                    values = {"value_bool": bool(raw)}
                elif raw:
                    values = {"value_char": raw.strip()}
                else:
                    continue
                request.env["tour.booking.answer"].sudo().create(dict(
                    values,
                    booking_id=booking_sudo.id,
                    question_id=question.id,
                    participant_index=index,
                ))

    @http.route(
        ["/tour/booking/<int:booking_id>/cancel"],
        type="http", auth="public", website=True, methods=["POST"],
    )
    def cancel(self, booking_id, access_token=None, **post):
        """Let the guest cancel from their own booking page.

        The refund is worked out by the model against the moment of
        cancellation; nothing about it is decided here, and nothing the browser
        sends influences it.
        """
        try:
            booking_sudo = self._booking_from_token(booking_id, access_token)
        except (AccessError, MissingError):
            return request.redirect("/tours")
        try:
            booking_sudo.action_cancel()
        except UserError as error:
            return request.redirect("%s&error=%s" % (
                booking_sudo._checkout_url(), error.args[0] if error.args else "",
            ))
        return request.redirect(booking_sudo._checkout_url())

    # --- Payment -----------------------------------------------------------

    @http.route(
        ["/tour/booking/<int:booking_id>/transaction"],
        type="jsonrpc", auth="public",
    )
    def transaction(self, booking_id, access_token=None, **kwargs):
        """Open a payment transaction against the booking.

        The booking is linked to the transaction at creation, which is what lets
        `payment.transaction._post_process` find it again on the way back
        without trusting anything the browser returns.
        """
        booking_sudo = self._booking_from_token(booking_id, access_token)
        if booking_sudo.state != "draft":
            raise ValidationError(_("This booking has already been paid for."))

        # Required answers are checked before taking money, not after. Being
        # asked for a shoe size after paying is a bad experience; discovering
        # the booking cannot be confirmed after paying is a refund.
        booking_sudo._check_required_answers()

        self._validate_transaction_kwargs(kwargs)
        # Amount and currency are re-derived here rather than taken from the
        # browser, and they are the *settlement* pair: the provider is asked for
        # euros it can settle, at a rate this booking fixed when it was created,
        # so nothing is converted between here and the callback.
        amount, currency = booking_sudo.payment_amount()
        kwargs.update({
            "partner_id": booking_sudo.partner_id.id,
            "currency_id": currency.id,
            "amount": amount,
        })
        transaction_sudo = self._create_transaction(
            custom_create_values={"tour_booking_ids": [Command.set([booking_sudo.id])]},
            **kwargs,
        )
        return transaction_sudo._get_processing_values()
