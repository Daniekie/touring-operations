from odoo.exceptions import ValidationError

from .common import TourCase


class TestPricing(TourCase):
    """Every total is computed on the server. A price from the browser is not
    input, not even as a cross-check."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.wetsuit = cls.env["tour.extra"].create({
            "name": "Wetsuit",
            "price": 10.0,
            "price_basis": "per_person",
            "is_taxable": True,
        })
        cls.pickup = cls.env["tour.extra"].create({
            "name": "Hotel Pickup",
            "price": 25.0,
            "price_basis": "per_booking",
            "is_taxable": False,
        })
        cls.tour.extra_ids = [(6, 0, (cls.wetsuit | cls.pickup).ids)]

    def test_the_base_price_is_the_per_person_price_times_the_party(self):
        booking = self._booking(pax=3)

        self.assertEqual(booking.amount_untaxed, 150.0)
        self.assertEqual(booking.amount_total, 150.0)

    def test_a_per_person_extra_is_charged_for_every_participant(self):
        booking = self._booking(pax=3)

        self.env["tour.booking.extra"].create({
            "booking_id": booking.id,
            "extra_id": self.wetsuit.id,
            "quantity": 1,
        })

        # 3 x 50 for the dive, plus 3 x 10 for the wetsuits.
        self.assertEqual(booking.amount_total, 180.0)

    def test_a_per_booking_extra_is_charged_once_however_big_the_party(self):
        booking = self._booking(pax=4)

        self.env["tour.booking.extra"].create({
            "booking_id": booking.id,
            "extra_id": self.pickup.id,
            "quantity": 1,
        })

        # 4 x 50 for the dive, plus one van.
        self.assertEqual(booking.amount_total, 225.0)

    def test_an_extras_price_is_frozen_at_the_moment_it_is_bought(self):
        """Raising next season's wetsuit price must not reprice last season's
        bookings."""
        booking = self._booking(pax=1)
        line = self.env["tour.booking.extra"].create({
            "booking_id": booking.id,
            "extra_id": self.wetsuit.id,
            "quantity": 1,
        })

        self.wetsuit.price = 99.0

        self.assertEqual(line.unit_price, 10.0)
        self.assertEqual(booking.amount_total, 60.0)

    def test_an_extra_cannot_exceed_its_maximum_quantity(self):
        self.wetsuit.max_quantity = 2
        booking = self._booking(pax=4)

        with self.assertRaises(ValidationError):
            self.env["tour.booking.extra"].create({
                "booking_id": booking.id,
                "extra_id": self.wetsuit.id,
                "quantity": 3,
            })

    def test_tax_applies_to_the_tour_and_to_taxable_extras_only(self):
        self.tour.tax_ids = [(6, 0, self._tax(6.0).ids)]

        booking = self._booking(pax=2)
        self.env["tour.booking.extra"].create({
            "booking_id": booking.id,
            "extra_id": self.wetsuit.id,   # taxable
            "quantity": 1,
        })
        self.env["tour.booking.extra"].create({
            "booking_id": booking.id,
            "extra_id": self.pickup.id,    # not taxable
            "quantity": 1,
        })

        # Taxable base: 2 x 50 + 2 x 10 = 120. Tax: 7.20. Untaxed also carries
        # the 25 pickup, which is outside the tax base entirely.
        self.assertAlmostEqual(booking.amount_tax, 7.20, places=2)
        self.assertAlmostEqual(booking.amount_untaxed, 145.0, places=2)
        self.assertAlmostEqual(booking.amount_total, 152.20, places=2)

    def test_the_total_follows_a_change_in_party_size(self):
        booking = self._booking(pax=2)
        self.env["tour.booking.extra"].create({
            "booking_id": booking.id,
            "extra_id": self.wetsuit.id,
            "quantity": 1,
        })
        self.assertEqual(booking.amount_total, 120.0)

        booking.pax = 3

        self.assertEqual(
            booking.amount_total, 180.0,
            "A per-person extra must follow the party size it was bought for.",
        )
