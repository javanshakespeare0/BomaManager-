import os
import unittest
from datetime import date, datetime, timedelta

os.environ['APP_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite://'

from app import Room, RoomRequest, Property, User, app, db


class RoomAssignmentTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.landlord = User(
                email='landlord@example.test',
                password='unused',
                role='landlord',
                is_landlord=True,
                subscription_status='active',
                subscription_expiry=datetime.utcnow() + timedelta(days=30),
            )
            db.session.add(self.landlord)
            db.session.flush()
            self.tenant = User(
                email='tenant@example.test',
                password='unused',
                role='tenant',
                landlord_id=self.landlord.id,
                name='Tenant One',
            )
            self.property = Property(
                name='Test Property',
                location='Test Location',
                landlord_id=self.landlord.id,
            )
            db.session.add_all([self.tenant, self.property])
            db.session.flush()
            self.room = Room(
                room_number='101',
                rent_amount=10000,
                property_id=self.property.id,
            )
            db.session.add(self.room)
            db.session.commit()
            self.landlord_id = self.landlord.id
            self.tenant_id = self.tenant.id
            self.room_id = self.room.id
            self.property_id = self.property.id
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.landlord_id)
            session['_fresh'] = True

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_assignment_page_has_one_assignment_form_and_links_add_tenant(self):
        response = self.client.get(f'/assign_tenant/{self.room_id}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.count(b'<form'), 1)
        self.assertIn(b'Add tenant', response.data)
        self.assertNotIn(b'Add New Tenant', response.data)

    def test_landlord_can_assign_a_linked_tenant(self):
        response = self.client.post(
            f'/assign_tenant/{self.room_id}',
            data={'tenant_id': str(self.tenant_id), 'assigned_date': date.today().isoformat()},
        )

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            room = db.session.get(Room, self.room_id)
            self.assertEqual(room.tenant_id, self.tenant_id)
            self.assertTrue(room.is_occupied)
            self.assertEqual(room.assigned_date, date.today())

    def test_approved_request_keeps_room_visible_in_landlord_dashboard(self):
        with app.app_context():
            room_request = RoomRequest(room_id=self.room_id, tenant_id=self.tenant_id)
            db.session.add(room_request)
            db.session.commit()
            request_id = room_request.id

        response = self.client.post(
            f'/room-requests/{request_id}/approve',
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Room 101', response.data)
        self.assertIn(b'tenant@example.test', response.data)
        with app.app_context():
            room = db.session.get(Room, self.room_id)
            self.assertEqual(room.tenant_id, self.tenant_id)
            self.assertTrue(room.is_occupied)
            self.assertEqual(
                RoomRequest.query.filter_by(id=request_id).one().status,
                'approved',
            )

    def test_tenant_already_assigned_cannot_be_assigned_a_second_room(self):
        with app.app_context():
            room = db.session.get(Room, self.room_id)
            room.tenant_id = self.tenant_id
            room.is_occupied = True
            second_room = Room(
                room_number='102',
                rent_amount=10000,
                property_id=self.property_id,
            )
            db.session.add(second_room)
            db.session.commit()
            second_room_id = second_room.id

        response = self.client.post(
            f'/assign_tenant/{second_room_id}',
            data={'tenant_id': str(self.tenant_id), 'assigned_date': date.today().isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'already has an assigned room', response.data)
