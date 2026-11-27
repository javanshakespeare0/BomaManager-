import os
import unittest

os.environ['APP_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite://'

from app import User, app, db


class RegistrationPhoneTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with app.app_context():
            db.drop_all()
            db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_registration_requires_phone_number(self):
        response = self.client.post('/register', data={
            'name': 'New Landlord',
            'email': 'landlord@example.test',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'role': 'landlord',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Complete all required account details.', response.data)
        with app.app_context():
            self.assertIsNone(User.query.filter_by(email='landlord@example.test').first())

    def test_registration_saves_normalized_phone_number(self):
        response = self.client.post('/register', data={
            'name': 'New Landlord',
            'email': 'landlord@example.test',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'role': 'landlord',
            'phone': '0712345678',
        })

        self.assertEqual(response.status_code, 302)
        with app.app_context():
            user = User.query.filter_by(email='landlord@example.test').one()
            self.assertEqual(user.contact_number, '+254712345678')


if __name__ == '__main__':
    unittest.main()
