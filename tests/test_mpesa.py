import base64
import unittest
from unittest.mock import Mock, patch

from mpesa import stk_push2


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


if __name__ == '__main__':
    unittest.main()
