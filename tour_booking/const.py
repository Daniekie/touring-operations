"""Values shared by more than one model.

Kept here rather than repeated so that a selection can never drift between the
model that writes it and the model that reads it.
"""

# How a price scales with the size of the party.
PRICE_BASIS = [
    ("per_person", "Per person"),
    ("per_booking", "Per booking"),
]

# Booking states that occupy a seat on a departure. A draft counts: it is a
# checkout in flight, and if it did not hold its seats two guests could pay for
# the same last place. Drafts are released by the reaper in tour_booking.py.
SEAT_HOLDING_STATES = ("draft", "confirmed")

# The only payment states that mean a checkout is definitively over and its
# seats can go back on sale. Everything else — including `done`, which on a
# still-draft booking means post-processing has not caught up yet — leaves the
# booking alone however old it is. Bank transfers and iDEAL settle long after
# any sensible reaper cutoff.
DEAD_TRANSACTION_STATES = ("cancel", "error")

WEEKDAYS = [
    ("mon", "Monday"),
    ("tue", "Tuesday"),
    ("wed", "Wednesday"),
    ("thu", "Thursday"),
    ("fri", "Friday"),
    ("sat", "Saturday"),
    ("sun", "Sunday"),
]
