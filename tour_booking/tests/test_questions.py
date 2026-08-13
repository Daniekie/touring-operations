from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tools import mute_logger

from .common import TourCase


class TestQuestions(TourCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shoe_size = cls.env["tour.question"].create({
            "name": "Shoe size",
            "field_type": "text",
            "scope": "per_person",
            "required": True,
        })
        cls.hotel = cls.env["tour.question"].create({
            "name": "Which hotel?",
            "field_type": "text",
            "scope": "per_booking",
            "required": False,
        })
        cls.level = cls.env["tour.question"].create({
            "name": "Certification level",
            "field_type": "select",
            "scope": "per_booking",
            "answer_options": "Open Water\nAdvanced\nDivemaster",
        })
        cls.tour.question_ids = [
            (6, 0, (cls.shoe_size | cls.hotel | cls.level).ids)
        ]

    def test_an_answer_attaches_to_its_booking(self):
        booking = self._booking(pax=1)

        answer = self.env["tour.booking.answer"].create({
            "booking_id": booking.id,
            "question_id": self.hotel.id,
            "value_char": "Hotel Bonaire",
        })

        self.assertIn(answer, booking.answer_ids)

    def test_a_choice_question_only_accepts_one_of_its_choices(self):
        booking = self._booking(pax=1)

        with self.assertRaises(ValidationError):
            self.env["tour.booking.answer"].create({
                "booking_id": booking.id,
                "question_id": self.level.id,
                "value_char": "Submarine Captain",
            })

        self.assertTrue(self.env["tour.booking.answer"].create({
            "booking_id": booking.id,
            "question_id": self.level.id,
            "value_char": "Advanced",
        }))

    def test_a_per_person_question_is_asked_of_each_participant(self):
        booking = self._booking(pax=2)

        for index in (1, 2):
            self.env["tour.booking.answer"].create({
                "booking_id": booking.id,
                "question_id": self.shoe_size.id,
                "participant_index": index,
                "value_char": "42",
            })

        self.assertEqual(len(booking.answer_ids), 2)

    def test_a_per_person_answer_needs_a_participant_within_the_party(self):
        booking = self._booking(pax=2)

        with self.assertRaises(ValidationError):
            self.env["tour.booking.answer"].create({
                "booking_id": booking.id,
                "question_id": self.shoe_size.id,
                "participant_index": 3,
                "value_char": "42",
            })

    def test_the_same_question_cannot_be_answered_twice_for_one_participant(self):
        booking = self._booking(pax=1)
        values = {
            "booking_id": booking.id,
            "question_id": self.shoe_size.id,
            "participant_index": 1,
            "value_char": "42",
        }
        self.env["tour.booking.answer"].create(values)

        # The savepoint matters: a violated constraint aborts the transaction,
        # and without rolling back to a known point every later statement in
        # this test — including the teardown — fails for the wrong reason.
        # Muted because `odoo.sql_db` logs the failing query at ERROR level
        # whether or not the caller is expecting it.
        with mute_logger("odoo.sql_db"), self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.env["tour.booking.answer"].create(dict(values, value_char="43"))
                self.env.flush_all()

    def test_a_required_question_blocks_confirmation_until_it_is_answered(self):
        """Enforced at confirmation, not at create: a checkout is built up over
        several steps, and a draft that cannot be saved until every answer is in
        is a checkout that cannot be built."""
        booking = self._booking(pax=2)

        with self.assertRaises(UserError):
            booking.action_confirm()

        for index in (1, 2):
            self.env["tour.booking.answer"].create({
                "booking_id": booking.id,
                "question_id": self.shoe_size.id,
                "participant_index": index,
                "value_char": "42",
            })

        booking.action_confirm()
        self.assertEqual(booking.state, "confirmed")

    def test_a_partly_answered_per_person_question_still_blocks_confirmation(self):
        booking = self._booking(pax=2)
        self.env["tour.booking.answer"].create({
            "booking_id": booking.id,
            "question_id": self.shoe_size.id,
            "participant_index": 1,
            "value_char": "42",
        })

        with self.assertRaises(
            UserError,
            msg="One participant answered and the booking confirmed anyway.",
        ):
            booking.action_confirm()

    def test_an_optional_question_never_blocks_confirmation(self):
        self.shoe_size.required = False
        booking = self._booking(pax=2)

        booking.action_confirm()

        self.assertEqual(booking.state, "confirmed")

    def test_a_choice_question_must_offer_choices(self):
        with self.assertRaises(ValidationError):
            self.env["tour.question"].create({
                "name": "Empty choice",
                "field_type": "select",
                "answer_options": "",
            })
