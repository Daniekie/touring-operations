"""Give bookings made before this version the price they were sold at.

`tour.booking.price_per_person` and `tour.booking.tax_ids` used to be read
through the tour. Bookings that existed before the columns did have nothing in
them, and a booking with no price of its own prices its seats at zero the next
time anything touches it — so this is not an optional tidy-up, it is what stops
the upgrade from quietly zeroing every historical total.

The tour's current price is the best available answer. It is the right one
unless the price has already been changed since the booking was taken, in which
case the old behaviour was reading that same current price anyway: nothing is
lost that was not already lost.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE tour_booking booking
           SET price_per_person = tour.price_per_person
          FROM tour_departure departure, tour_tour tour
         WHERE booking.departure_id = departure.id
           AND departure.tour_id = tour.id
           AND booking.price_per_person IS NULL
    """)

    cr.execute("""
        INSERT INTO account_tax_tour_booking_rel (tour_booking_id, account_tax_id)
             SELECT booking.id, tour_tax.account_tax_id
               FROM tour_booking booking
               JOIN tour_departure departure ON departure.id = booking.departure_id
               JOIN account_tax_tour_tour_rel tour_tax
                 ON tour_tax.tour_tour_id = departure.tour_id
        ON CONFLICT DO NOTHING
    """)
