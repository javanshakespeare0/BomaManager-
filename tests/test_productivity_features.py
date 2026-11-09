import io
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from openpyxl import load_workbook

os.environ['APP_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite://'

from app import (
    MaintenanceRequest,
    Payment,
    PaymentReminder,
    Property,
    PendingBill,
    Room,
    RoomRequest,
    User,
    WaterBill,
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
        self.assertIn(b'class="tenant-room-number">Room 101', response.data)
        self.assertIn(b'/reports', response.data)
        self.assertIn(b'Room application', response.data)
        self.assertIn(b'Vacant room', response.data)
        self.assertIn(f'/room-requests/{application_id}/approve'.encode(), response.data)
        self.assertIn(f'/assign_tenant/{vacant_room_id}'.encode(), response.data)
        self.assertIn(b'Approve this application and assign the room', response.data)
        self.assertLess(response.data.index(b'Urgent leak'), response.data.index(b'Applicant Two'))

    def test_my_properties_groups_locations_and_updates_room_payment_in_place(self):
        with app.app_context():
            second_property = Property(
                name='Riverside Apartments',
                location='Riverside',
                landlord_id=self.landlord_id,
            )
            db.session.add(second_property)
            db.session.flush()
            vacant_room = Room(
                room_number='A2',
                room_type='Bedsitter',
                rent_amount=8000,
                property_id=second_property.id,
                is_occupied=False,
            )
            db.session.add(vacant_room)
            db.session.commit()
            vacant_room_id = vacant_room.id
        self.login_as(self.landlord_id)

        locations_page = self.client.get('/my-properties')
        location_page = self.client.get('/my-properties?location=Test+Location')

        self.assertEqual(locations_page.status_code, 200)
        self.assertIn(b'Test Location', locations_page.data)
        self.assertIn(b'Riverside', locations_page.data)
        self.assertEqual(location_page.status_code, 200)
        self.assertIn(b'Test Property', location_page.data)
        self.assertIn(b'Room 101', location_page.data)
        self.assertIn(b'Tenant One', location_page.data)
        self.assertIn(b'Balance due', location_page.data)
        self.assertIn(b'Manage other bills', location_page.data)
        self.assertIn(b'/mark_rent_paid/', location_page.data)
        self.assertNotIn(b'Riverside Apartments', location_page.data)

        paid_response = self.client.post(
            f'/mark_rent_paid/{self.room_id}',
            data={'return_to': '/my-properties?location=Test+Location'},
        )

        self.assertEqual(paid_response.status_code, 302)
        self.assertEqual(paid_response.location, '/my-properties?location=Test+Location')
        with app.app_context():
            payment = Payment.query.filter_by(room_id=self.room_id).one()
            self.assertEqual(payment.amount, 10000)

        return_query = 'return_to=%2Fmy-properties%3Flocation%3DTest%2BLocation'
        pending_bill_url = f'/pending_bill/{self.room_id}?{return_query}'
        pending_page = self.client.get(pending_bill_url)
        self.assertIn(b'href="/my-properties?location=Test+Location"', pending_page.data)
        self.assertIn(b'Back to properties', pending_page.data)
        pending_response = self.client.post(
            pending_bill_url,
            data={'title': 'Cleaning', 'amount': '500', 'note': 'Monthly cleaning'},
        )
        self.assertEqual(pending_response.location, '/my-properties?location=Test+Location')
        with app.app_context():
            pending_bill = PendingBill.query.filter_by(room_id=self.room_id).one()
            self.assertEqual(pending_bill.amount, 500)

        water_bill_url = f'/water_bill/{self.room_id}?{return_query}'
        water_response = self.client.post(
            water_bill_url,
            data={'units_used': '3', 'rate_per_unit': '100'},
        )
        self.assertEqual(water_response.location, '/my-properties?location=Test+Location')
        with app.app_context():
            water_bill = WaterBill.query.filter_by(room_id=self.room_id).one()
            self.assertEqual(water_bill.amount, 300)

        vacant_location_page = self.client.get('/my-properties?location=Riverside')
        self.assertEqual(vacant_location_page.status_code, 200)
        self.assertIn(f'/assign_tenant/{vacant_room_id}'.encode(), vacant_location_page.data)
        self.assertIn(b'Vacant', vacant_location_page.data)

    def test_tenants_cannot_open_landlord_property_workspace(self):
        self.login_as(self.tenant_id)

        response = self.client.get('/my-properties')

        self.assertEqual(response.status_code, 403)

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
        current_period = date.today().replace(day=1).isoformat()
        with app.app_context():
            db.session.add(Payment(
                amount=2500,
                month=current_period,
                date_paid=datetime.now(),
                mpesa_code='TEST-RECEIPT',
                room_id=self.room_id,
                tenant_id=self.tenant_id,
            ))
            db.session.commit()
        self.login_as(self.landlord_id)

        page = self.client.get('/reports')
        export = self.client.get('/reports?export=csv')
        excel_export = self.client.get('/reports?export=xlsx')

        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Collected this month', page.data)
        self.assertIn(b'Outstanding balances', page.data)
        self.assertEqual(export.status_code, 200)
        self.assertIn('text/csv', export.content_type)
        self.assertIn(b'Tenant One', export.data)
        self.assertIn(b'Outstanding balance (Ksh)', export.data)
        self.assertEqual(excel_export.status_code, 200)
        self.assertIn('spreadsheetml.sheet', excel_export.content_type)
        workbook = load_workbook(io.BytesIO(excel_export.data), data_only=True)
        self.assertEqual(workbook.sheetnames, ['Portfolio Summary', 'Tenant Ledger', 'Payment History'])
        ledger = workbook['Tenant Ledger']
        self.assertEqual(ledger['A5'].value, 'Test Property')
        self.assertEqual(ledger['B5'].value, '101')
        self.assertEqual(ledger['C5'].value, 'Tenant One')
        self.assertEqual(ledger['J5'].value, 2500)
        self.assertEqual(ledger['K5'].value, 7500)
        self.assertEqual(workbook['Payment History']['I5'].value, 'TEST-RECEIPT')

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
