import base64
import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

from mpesa import stk_push2

os.environ['APP_ENV'] = 'testing'
os.environ['DATABASE_URL'] = 'sqlite://'

import app as app_module
from app import (
    Payment,
    PaymentAttempt,
    Property,
    Room,
    SubscriptionPaymentAttempt,
    User,
    app,
    db,
)


class StkPushTests(unittest.TestCase):
    @patch('mpesa.requests.post')
    @patch('mpesa.requests.get')
    def test_sends_authenticated_stk_request(self, get, post):
        token_response = Mock(ok=True)
        token_response.json.return_value = {'access_token': 'test-access-token'}
        stk_response = Mock(ok=True)
        stk_response.json.return_value = {
            'ResponseCode': '0',
            'CheckoutRequestID': 'checkout-123',
        }
        get.return_value = token_response
        post.return_value = stk_response

        result = stk_push2(
            '254712345678',
            1250,
            consumer_key='consumer-key',
            consumer_secret='consumer-secret',
            business_shortcode='174379',
            passkey='test-passkey',
            callback_url='https://example.test/callback',
        )

        self.assertEqual(result['ResponseCode'], '0')
        self.assertEqual(
            post.call_args.kwargs['headers']['Authorization'],
            'Bearer test-access-token',
        )
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['Amount'], 1250)
        self.assertEqual(payload['PhoneNumber'], '254712345678')
        self.assertEqual(payload['CallBackURL'], 'https://example.test/callback')
        self.assertEqual(
            base64.b64decode(payload['Password']).decode(),
            f"174379test-passkey{payload['Timestamp']}",
        )

    @patch('mpesa.requests.post')
    @patch('mpesa.requests.get')
    def test_rejects_non_object_stk_response(self, get, post):
        token_response = Mock(ok=True)
        token_response.json.return_value = {'access_token': 'test-access-token'}
        stk_response = Mock(ok=True)
        stk_response.json.return_value = ['unexpected']
        get.return_value = token_response
        post.return_value = stk_response

        with self.assertRaisesRegex(ValueError, 'must be a JSON object'):
            stk_push2(
                '254712345678',
                1250,
                consumer_key='consumer-key',
                consumer_secret='consumer-secret',
                business_shortcode='174379',
                passkey='test-passkey',
                callback_url='https://example.test/callback',
            )

    @patch('mpesa.requests.post')
    @patch('mpesa.requests.get')
    def test_rejects_fractional_shilling_amount_before_request(self, get, post):
        with self.assertRaisesRegex(ValueError, 'positive whole number'):
            stk_push2(
                '254712345678',
                1250.5,
                consumer_key='consumer-key',
                consumer_secret='consumer-secret',
                business_shortcode='174379',
                passkey='test-passkey',
                callback_url='https://example.test/callback',
            )

        get.assert_not_called()
        post.assert_not_called()


class MpesaFlowTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.previous_mpesa_config = {
            'CONSUMER_KEY': app_module.CONSUMER_KEY,
            'CONSUMER_SECRET': app_module.CONSUMER_SECRET,
            'BUSINESS_SHORTCODE': app_module.BUSINESS_SHORTCODE,
            'PASSKEY': app_module.PASSKEY,
            'CALLBACK_URL': app_module.CALLBACK_URL,
            'SUBSCRIPTION_CALLBACK_URL': app_module.SUBSCRIPTION_CALLBACK_URL,
        }
        app_module.CONSUMER_KEY = 'test-consumer-key'
        app_module.CONSUMER_SECRET = 'test-consumer-secret'
        app_module.BUSINESS_SHORTCODE = '174379'
        app_module.PASSKEY = 'test-passkey'
        app_module.CALLBACK_URL = 'https://example.test/api/mpesa/callback'
        app_module.SUBSCRIPTION_CALLBACK_URL = 'https://example.test/api/mpesa/callback/subscription'
        with app.app_context():
            db.drop_all()
            db.create_all()
            landlord = User(
                email='landlord@example.test',
                password='unused',
                role='landlord',
                is_landlord=True,
                subscription_status='active',
                subscription_expiry=datetime.utcnow() + timedelta(days=30),
            )
            db.session.add(landlord)
            db.session.flush()
            tenant = User(
                email='tenant@example.test',
                password='unused',
                role='tenant',
                landlord_id=landlord.id,
            )
            property_record = Property(
                name='Test Property',
                location='Nairobi',
                landlord_id=landlord.id,
            )
            db.session.add_all([tenant, property_record])
            db.session.flush()
            room = Room(
                room_number='101',
                rent_amount=1000,
                property_id=property_record.id,
                tenant_id=tenant.id,
                is_occupied=True,
                assigned_date=date.today().replace(day=1),
            )
            db.session.add(room)
            db.session.commit()
            self.landlord_id = landlord.id
            self.tenant_id = tenant.id
            self.room_id = room.id
        self.client = app.test_client()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()
        for name, value in self.previous_mpesa_config.items():
            setattr(app_module, name, value)

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True

    @patch('app.stk_push2')
    def test_rent_prompt_tracks_and_records_successful_callback(self, stk_push):
        stk_push.return_value = {
            'ResponseCode': '0',
            'CheckoutRequestID': 'rent-checkout-1',
            'MerchantRequestID': 'rent-merchant-1',
        }
        self.login_as(self.tenant_id)

        invalid_phone = self.client.post(
            f'/stk_push/{self.room_id}',
            data={'phone': 'not-a-phone', 'amount': '500'},
        )
        self.assertEqual(invalid_phone.status_code, 302)
        stk_push.assert_not_called()

        fractional = self.client.post(
            f'/stk_push/{self.room_id}',
            data={'phone': '0712345678', 'amount': '500.50'},
        )
        self.assertEqual(fractional.status_code, 302)
        stk_push.assert_not_called()

        response = self.client.post(
            f'/stk_push/{self.room_id}',
            data={'phone': '0712345678', 'amount': '500'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(stk_push.call_args.args[0], '254712345678')
        with app.app_context():
            attempt = PaymentAttempt.query.one()
            self.assertEqual(attempt.amount, 500)

        callback = self.client.post('/api/mpesa/callback', json={
            'Body': {
                'stkCallback': {
                    'CheckoutRequestID': 'rent-checkout-1',
                    'ResultCode': 0,
                    'CallbackMetadata': {
                        'Item': [
                            {'Name': 'Amount', 'Value': 500},
                            {'Name': 'MpesaReceiptNumber', 'Value': 'RENT123'},
                        ],
                    },
                },
            },
        })

        self.assertEqual(callback.status_code, 200)
        with app.app_context():
            payment = Payment.query.one()
            self.assertEqual(payment.amount, 500)
            self.assertEqual(payment.mpesa_code, 'RENT123')

    def test_subscription_callback_rejects_underpayment(self):
        with app.app_context():
            attempt = SubscriptionPaymentAttempt(
                checkout_request_id='subscription-checkout-1',
                merchant_request_id='subscription-merchant-1',
                user_id=self.landlord_id,
                plan='pro',
            )
            db.session.add(attempt)
            landlord = db.session.get(User, self.landlord_id)
            landlord.subscription_status = 'expired'
            landlord.subscription_expiry = datetime.utcnow() - timedelta(days=1)
            db.session.commit()

        response = self.client.post('/api/mpesa/callback/subscription', json={
            'Body': {
                'stkCallback': {
                    'CheckoutRequestID': 'subscription-checkout-1',
                    'MerchantRequestID': 'subscription-merchant-1',
                    'ResultCode': 0,
                    'CallbackMetadata': {
                        'Item': [
                            {'Name': 'Amount', 'Value': 500},
                            {'Name': 'MpesaReceiptNumber', 'Value': 'SUB123'},
                        ],
                    },
                },
            },
        })

        self.assertEqual(response.status_code, 200)
        with app.app_context():
            landlord = db.session.get(User, self.landlord_id)
            attempt = db.session.get(
                SubscriptionPaymentAttempt,
                'subscription-checkout-1',
            )
            self.assertEqual(landlord.subscription_status, 'expired')
            self.assertEqual(attempt.outcome, 'rejected')

        with app.app_context():
            db.session.add(SubscriptionPaymentAttempt(
                checkout_request_id='subscription-checkout-2',
                merchant_request_id='subscription-merchant-2',
                user_id=self.landlord_id,
                plan='pro',
            ))
            db.session.commit()

        valid_response = self.client.post('/api/mpesa/callback/subscription', json={
            'Body': {
                'stkCallback': {
                    'CheckoutRequestID': 'subscription-checkout-2',
                    'MerchantRequestID': 'subscription-merchant-2',
                    'ResultCode': 0,
                    'CallbackMetadata': {
                        'Item': [
                            {'Name': 'Amount', 'Value': 1000},
                            {'Name': 'MpesaReceiptNumber', 'Value': 'SUB124'},
                        ],
                    },
                },
            },
        })

        self.assertEqual(valid_response.status_code, 200)
        with app.app_context():
            landlord = db.session.get(User, self.landlord_id)
            attempt = db.session.get(
                SubscriptionPaymentAttempt,
                'subscription-checkout-2',
            )
            self.assertEqual(landlord.subscription_status, 'active')
            self.assertEqual(landlord.subscription_plan, 'pro')
            self.assertEqual(attempt.outcome, 'activated')

    @patch('app.stk_push2')
    def test_subscription_prompt_records_checkout_reference(self, stk_push):
        stk_push.return_value = {
            'ResponseCode': '0',
            'CheckoutRequestID': 'subscription-checkout-3',
            'MerchantRequestID': 'subscription-merchant-3',
        }
        self.login_as(self.landlord_id)

        response = self.client.post(
            '/pay-subscription',
            data={'phone': '0712345678', 'plan': 'pro'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(stk_push.call_args.args[0], '254712345678')
        with app.app_context():
            attempt = SubscriptionPaymentAttempt.query.one()
            self.assertEqual(attempt.checkout_request_id, 'subscription-checkout-3')
            self.assertEqual(attempt.merchant_request_id, 'subscription-merchant-3')
            self.assertEqual(attempt.plan, 'pro')
            self.assertEqual(attempt.user_id, self.landlord_id)


if __name__ == '__main__':
    unittest.main()
