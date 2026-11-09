import io
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

os.environ['APP_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite://'

from app import (
    MaintenanceRequest,
    PaymentReminder,
    Property,
    Room,
    RoomRequest,
    User,
    app,
    db,
)


class ProductivityFeatureTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.uploads = tempfile.TemporaryDirectory()
        app.config['MAINTENANCE_UPLOAD_FOLDER'] = self.uploads.name
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
                contact_number='0712345678',
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
                tenant_id=self.tenant.id,
                is_occupied=True,
                assigned_date=date.today().replace(day=1),
            )
            db.session.add(self.room)
            db.session.commit()
            self.landlord_id = self.landlord.id
            self.tenant_id = self.tenant.id
            self.property_id = self.property.id
            self.room_id = self.room.id
        self.client = app.test_client()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
        self.uploads.cleanup()

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True

    def test_dashboard_prioritizes_followups_and_exposes_productivity_links(self):
        with app.app_context():
            applicant = User(
                email='applicant@example.test',
                password='unused',
                role='tenant',
                landlord_id=self.landlord_id,
                name='Applicant Two',
            )
            vacant_room = Room(
                room_number='102',
                room_type='One Bedroom',
                rent_amount=12000,
                property_id=self.property_id,
                is_occupied=False,
            )
            db.session.add(MaintenanceRequest(
                title='Urgent leak',
                description='Water is entering the unit.',
                priority='urgent',
                room_id=self.room_id,
                tenant_id=self.tenant_id,
            ))
            db.session.add_all([applicant, vacant_room])
            db.session.flush()
            application = RoomRequest(
                room_id=vacant_room.id,
                tenant_id=applicant.id,
            )
            db.session.add(application)
            db.session.commit()
            application_id = application.id
            vacant_room_id = vacant_room.id
        self.login_as(self.landlord_id)

        response = self.client.get('/dashboard')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Needs attention', response.data)
        self.assertIn(b'Copy reminder', response.data)
        self.assertIn(b'urgent', response.data)
        self.assertIn(b'/reports', response.data)
        self.assertIn(b'Room application', response.data)
        self.assertIn(b'Vacant room', response.data)
        self.assertIn(f'/room-requests/{application_id}/approve'.encode(), response.data)
        self.assertIn(f'/assign_tenant/{vacant_room_id}'.encode(), response.data)
        self.assertIn(b'Approve this application and assign the room', response.data)
        self.assertLess(response.data.index(b'Urgent leak'), response.data.index(b'Applicant Two'))

    def test_landlord_can_log_manual_payment_reminder(self):
        self.login_as(self.landlord_id)

        response = self.client.post(f'/payment-reminders/{self.room_id}')

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            reminder = PaymentReminder.query.one()
            self.assertEqual(reminder.room_id, self.room_id)
            self.assertEqual(reminder.tenant_id, self.tenant_id)
            self.assertEqual(reminder.channel, 'manual')
            self.assertEqual(reminder.amount, 10000)

    def test_payment_reminder_rejects_another_landlords_room(self):
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
            db.session.commit()
            other_landlord_id = other_landlord.id
        self.login_as(other_landlord_id)

        response = self.client.post(f'/payment-reminders/{self.room_id}')

        self.assertEqual(response.status_code, 404)
        with app.app_context():
            self.assertEqual(PaymentReminder.query.count(), 0)

    def test_reports_include_summary_and_csv_export(self):
        self.login_as(self.landlord_id)

        page = self.client.get('/reports')
        export = self.client.get('/reports?export=csv')

        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Collected this month', page.data)
        self.assertIn(b'Outstanding balances', page.data)
        self.assertEqual(export.status_code, 200)
        self.assertIn('text/csv', export.content_type)
        self.assertIn(b'Tenant One', export.data)
        self.assertIn(b'Outstanding balance (Ksh)', export.data)

    def test_maintenance_priority_and_private_photo_upload(self):
        self.login_as(self.tenant_id)
        image = b'\x89PNG\r\n\x1a\n' + b'\x00' * 24

        response = self.client.post(
            '/maintenance-requests',
            data={
                'title': 'Broken window',
                'description': 'The bedroom window is cracked.',
                'priority': 'high',
                'photo': (io.BytesIO(image), 'damage.png'),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'High priority', response.data)
        with app.app_context():
            item = MaintenanceRequest.query.one()
            self.assertEqual(item.priority, 'high')
            self.assertTrue(item.photo_path.endswith('.png'))
            item_id = item.id
        photo_response = self.client.get(f'/maintenance-photos/{item_id}')
        self.assertEqual(photo_response.status_code, 200)
        self.assertEqual(photo_response.headers.get('X-Content-Type-Options'), 'nosniff')
        photo_response.close()

    def test_maintenance_upload_rejects_non_image_payload(self):
        self.login_as(self.tenant_id)

        response = self.client.post(
            '/maintenance-requests',
            data={
                'title': 'Broken window',
                'description': 'The bedroom window is cracked.',
                'photo': (io.BytesIO(b'not an image'), 'damage.png'),
            },
            content_type='multipart/form-data',
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Attach a valid PNG', response.data)
        with app.app_context():
            self.assertEqual(MaintenanceRequest.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
