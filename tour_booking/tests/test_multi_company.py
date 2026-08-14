"""What a user of one company can see of another's.

Every model here that has a `company_id` had no record rule at all, so the
answer was "all of it": one operator's bookings, guests, prices and schedule
were readable — and writable — by a desk user of any other company on the same
instance. That is only invisible while an instance has one company on it, which
is the state every instance is in until the day it is not.
"""

from odoo.exceptions import AccessError

from .common import TourCase


class TestMultiCompany(TourCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_company = cls.env["res.company"].create({"name": "Other Operator"})

        # A desk user of the other company, and nothing else. `company_ids` is
        # what the record rules read; `company_id` alone would leave them
        # allowed everywhere they are a member.
        cls.other_user = cls.env["res.users"].create({
            "name": "Other Desk",
            "login": "other_desk",
            "company_id": cls.other_company.id,
            "company_ids": [(6, 0, cls.other_company.ids)],
            "group_ids": [(6, 0, [cls.env.ref("tour_booking.group_tour_user").id])],
        })

        # The fixtures from TourCase belong to the test company; give the other
        # one an experience of its own so "sees nothing" can be told apart from
        # "sees nothing because there is nothing".
        cls.other_tour = cls.env["tour.tour"].create({
            "name": "Their Dive",
            "company_id": cls.other_company.id,
            "duration_hours": 2.0,
            "default_capacity": 5,
            "price_per_person": 40.0,
        })

    def _as_other(self, model):
        return self.env[model].with_user(self.other_user)

    def test_a_user_does_not_see_another_companys_experiences(self):
        ours = self.tour

        visible = self._as_other("tour.tour").search([])

        self.assertIn(self.other_tour, visible)
        self.assertNotIn(ours, visible, "Another operator's catalogue was readable.")

    def test_a_user_does_not_see_another_companys_departures(self):
        departure = self._departure()

        self.assertNotIn(departure, self._as_other("tour.departure").search([]))

    def test_a_user_does_not_see_another_companys_bookings(self):
        booking = self._booking(pax=2)

        self.assertNotIn(
            booking, self._as_other("tour.booking").search([]),
            "Another operator's guest list was readable.",
        )

    def test_a_user_does_not_see_another_companys_extras(self):
        extra = self.env["tour.extra"].create({"name": "Ours", "price": 10.0})

        self.assertNotIn(extra, self._as_other("tour.extra").search([]))

    def test_reading_another_companys_booking_by_id_is_refused(self):
        """Search filters quietly; a direct read has to say no.

        A booking id is a small number in a URL, so "it will not turn up in a
        list" is not the guarantee that matters.
        """
        booking = self._booking(pax=2)

        with self.assertRaises(AccessError):
            self._as_other("tour.booking").browse(booking.id).read(["partner_id"])

    def test_the_records_that_belong_to_nobody_stay_shared(self):
        """Locations and cancellation policies carry no company at all.

        They are shared on purpose — one dive shop, one set of terms — and the
        rules must not turn a record nobody claimed into a record nobody can
        read.
        """
        location = self.env["tour.location"].create({"name": "The Pier"})
        policy = self.env["tour.cancellation.policy"].create({"name": "Shared terms"})

        self.assertIn(location, self._as_other("tour.location").search([]))
        self.assertIn(policy, self._as_other("tour.cancellation.policy").search([]))
