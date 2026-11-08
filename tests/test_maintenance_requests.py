import os
import unittest
from datetime import datetime, timedelta

os.environ['APP_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite://'

from app import MaintenanceRequest, Property, Room, User, app, db


class MaintenanceRequestTests(unittest.TestCase):
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
            self.other_tenant = User(
                email='other@example.test',
                password='unused',
                role='tenant',
                landlord_id=self.landlord.id,
            )
            self.property = Property(
                name='Test Property',
                location='Test Location',
                landlord_id=self.landlord.id,
            )
            db.session.add_all([self.tenant, self.other_tenant, self.property])
            db.session.flush()
            self.room = Room(
                room_number='101',
                rent_amount=10000,
                property_id=self.property.id,
                tenant_id=self.tenant.id,
                is_occupied=True,
            )
            db.session.add(self.room)
            db.session.commit()
            self.landlord_id = self.landlord.id
            self.tenant_id = self.tenant.id
            self.other_tenant_id = self.other_tenant.id
            self.room_id = self.room.id
        self.client = app.test_client()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True

    def test_tenant_can_submit_and_view_maintenance_request(self):
        self.login_as(self.tenant_id)
        response = self.client.post('/maintenance-requests', data={
            'title': 'Leaking tap',
            'description': 'The kitchen tap is leaking.',
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Leaking tap', response.data)
        with app.app_context():
            item = MaintenanceRequest.query.one()
            self.assertEqual(item.tenant_id, self.tenant_id)
            self.assertEqual(item.room_id, self.room_id)
            self.assertEqual(item.status, 'open')

    def test_landlord_can_update_request_status(self):
        with app.app_context():
            item = MaintenanceRequest(
                title='Broken light',
                description='The hallway light is out.',
                room_id=self.room_id,
                tenant_id=self.tenant_id,
            )
            db.session.add(item)
            db.session.commit()
            item_id = item.id
        self.login_as(self.landlord_id)

        response = self.client.post('/maintenance-requests', data={
            'request_id': str(item_id),
            'status': 'in_progress',
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        with app.app_context():
            self.assertEqual(db.session.get(MaintenanceRequest, item_id).status, 'in_progress')

    def test_tenant_cannot_change_request_status(self):
        with app.app_context():
            item = MaintenanceRequest(
                title='Broken light',
                description='The hallway light is out.',
                room_id=self.room_id,
                tenant_id=self.tenant_id,
            )
            db.session.add(item)
            db.session.commit()
            item_id = item.id
        self.login_as(self.tenant_id)

        response = self.client.post('/maintenance-requests', data={
            'request_id': str(item_id),
            'status': 'resolved',
        })

        self.assertEqual(response.status_code, 403)
        with app.app_context():
            self.assertEqual(db.session.get(MaintenanceRequest, item_id).status, 'open')

    def test_landlord_cannot_update_another_landlords_request(self):
        with app.app_context():
            other_landlord = User(
                email='other-landlord@example.test',
                password='unused',
                role='landlord',
                is_landlord=True,
                subscription_status='active',
                subscription_expiry=datetime.utcnow() + timedelta(days=30),
            )
            db.session.add(other_landlord)
            db.session.flush()
            other_property = Property(
                name='Other Property',
                location='Other Location',
                landlord_id=other_landlord.id,
            )
            db.session.add(other_property)
            db.session.flush()
            other_room = Room(
                room_number='201',
                rent_amount=10000,
                property_id=other_property.id,
                tenant_id=self.other_tenant_id,
                is_occupied=True,
            )
            db.session.add(other_room)
            item = MaintenanceRequest(
                title='Private issue',
                description='This belongs to another landlord.',
                room=other_room,
                tenant_id=self.other_tenant_id,
            )
            db.session.add(item)
            db.session.commit()
            item_id = item.id
        self.login_as(self.landlord_id)

        response = self.client.post('/maintenance-requests', data={
            'request_id': str(item_id),
            'status': 'resolved',
        })

        self.assertEqual(response.status_code, 404)
        with app.app_context():
            self.assertEqual(db.session.get(MaintenanceRequest, item_id).status, 'open')


if __name__ == '__main__':
    unittest.main()
