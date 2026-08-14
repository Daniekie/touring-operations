"""Demo bookings.

Kept in their own file, and out of `tour_booking.py`, because they are not part
of the model — they are fixtures that happen to need Python. They cannot be
written as XML records: a booking needs a departure, and departures do not exist
until the generator has run over the demo availability rules, so there is no
xml id to point a `<field ref=...>` at. This picks real departures out of the
schedule that was just generated.
"""

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

# tour, guest, party size, and which of that tour's upcoming departures to take.
# `nth` spreads them across the week so the calendar has more than one busy day.
#
# The answers are not decoration. Scuba and Klein Bonaire both ask required
# questions, and `action_confirm` refuses a booking that has not answered them —
# so a demo booking without answers would be stuck in draft and then reaped.
DEMO_BOOKINGS = [
    {
        "tour": "demo_tour_sunset",
        "guest": "demo_partner_hartman",
        "pax": 2,
        "nth": 0,
        "extras": [("demo_extra_gopro", 1)],
        "answers": [("demo_question_hotel", 0, "Divi Flamingo Beach Resort")],
    },
    {
        "tour": "demo_tour_sunset",
        "guest": "demo_partner_okafor",
        "pax": 4,
        "nth": 2,
        "extras": [("demo_extra_pickup", 1)],
        "answers": [("demo_question_hotel", 0, "Delfins Beach Resort")],
    },
    {
        "tour": "demo_tour_scuba",
        "guest": "demo_partner_lindqvist",
        "pax": 2,
        "nth": 0,
        "extras": [("demo_extra_wetsuit", 1)],
        "answers": [
            ("demo_question_certification", 1, "Advanced Open Water"),
            ("demo_question_certification", 2, "Open Water"),
            ("demo_question_shoe_size", 1, "44"),
            ("demo_question_shoe_size", 2, "39"),
            ("demo_question_hotel", 0, "Buddy Dive Resort"),
        ],
    },
    {
        "tour": "demo_tour_klein",
        "guest": "demo_partner_moreno",
        "pax": 3,
        "nth": 0,
        "extras": [("demo_extra_snorkel", 1)],
        "answers": [
            ("demo_question_shoe_size", 1, "41"),
            ("demo_question_shoe_size", 2, "38"),
            ("demo_question_shoe_size", 3, "36"),
            ("demo_question_swimmer", 0, True),
        ],
    },
    {
        "tour": "demo_tour_sailing",
        "guest": "demo_partner_becker",
        "pax": 2,
        "nth": 1,
        "extras": [],
        "answers": [("demo_question_swimmer", 0, True)],
    },
    # One cancelled, so the list has a muted row and the refund fields on the
    # form have something in them.
    {
        "tour": "demo_tour_sailing",
        "guest": "demo_partner_tanaka",
        "pax": 2,
        "nth": 3,
        "extras": [("demo_extra_snorkel", 1)],
        "answers": [],
        "cancelled": True,
    },
]


class TourBookingDemo(models.Model):
    _inherit = "tour.booking"

    @api.model
    def _demo_create_bookings(self):
        """Seed a handful of bookings across the generated schedule.

        Runs once. `<function>` in a demo file fires again on every module
        upgrade, and creating bookings is not idempotent the way generating
        departures is — so the presence of any booking at all is taken as "this
        database has been seeded", which also stops it trampling a database
        somebody has started using.
        """
        if self.search_count([], limit=1):
            return self.browse()

        # Far enough out to clear every demo tour's booking cut-off, the longest
        # of which is 24 hours.
        earliest = fields.Datetime.now() + relativedelta(days=3)
        bookings = self.browse()

        for spec in DEMO_BOOKINGS:
            tour = self.env.ref("tour_booking.%s" % spec["tour"], raise_if_not_found=False)
            guest = self.env.ref("tour_booking.%s" % spec["guest"], raise_if_not_found=False)
            if not tour or not guest:
                continue

            departures = self.env["tour.departure"].search(
                [
                    ("tour_id", "=", tour.id),
                    ("state", "=", "open"),
                    ("start_datetime", ">=", earliest),
                ],
                order="start_datetime",
                limit=spec["nth"] + 1,
            )
            if len(departures) <= spec["nth"]:
                continue

            booking = self.create({
                "departure_id": departures[spec["nth"]].id,
                "partner_id": guest.id,
                "pax": spec["pax"],
            })
            booking._demo_add_extras(spec["extras"])
            booking._demo_add_answers(spec["answers"])
            booking.action_confirm()
            if spec.get("cancelled"):
                booking.action_cancel()
            bookings |= booking

        return bookings

    def _demo_add_extras(self, extras):
        self.ensure_one()
        for xmlid, quantity in extras:
            extra = self.env.ref("tour_booking.%s" % xmlid, raise_if_not_found=False)
            if extra:
                self.env["tour.booking.extra"].create({
                    "booking_id": self.id,
                    "extra_id": extra.id,
                    # Deliberately 1 for a per-person extra: the subtotal
                    # already multiplies by the party size, so a quantity of 3
                    # here would be three wetsuits each.
                    "quantity": quantity,
                })

    def _demo_add_answers(self, answers):
        self.ensure_one()
        for xmlid, index, value in answers:
            question = self.env.ref("tour_booking.%s" % xmlid, raise_if_not_found=False)
            if not question:
                continue
            vals = {
                "booking_id": self.id,
                "question_id": question.id,
                "participant_index": index,
            }
            if question.field_type == "bool":
                vals["value_bool"] = bool(value)
            else:
                vals["value_char"] = value
            self.env["tour.booking.answer"].create(vals)
