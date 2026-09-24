import base64
import os
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth


DARAJA_ENV = os.getenv('DARAJA_ENV', os.getenv('MPESA_ENV', 'sandbox')).lower()
DARAJA_BASE_URL = (
    'https://api.safaricom.co.ke'
    if DARAJA_ENV == 'production'
    else 'https://sandbox.safaricom.co.ke'
)
CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY', '')
CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET', '')
BUSINESS_SHORTCODE = os.getenv('MPESA_BUSINESS_SHORTCODE', '174379')
PASSKEY = os.getenv('MPESA_PASSKEY', '')
CALLBACK_URL = os.getenv(
    'MPESA_CALLBACK_URL',
    'https://your-public-domain.example/api/mpesa/callback',
)


def stk_push2(
    phone,
    amount,
    account_reference='BomaManager',
    description='Rent payment',
    consumer_key=None,
    consumer_secret=None,
    business_shortcode=None,
    passkey=None,
    callback_url=None,
):
    """Send an STK Push and return Daraja's decoded response."""
    consumer_key = consumer_key or CONSUMER_KEY
    consumer_secret = consumer_secret or CONSUMER_SECRET
    business_shortcode = business_shortcode or BUSINESS_SHORTCODE
    passkey = passkey or PASSKEY
    callback_url = callback_url or CALLBACK_URL
    if not all((consumer_key, consumer_secret, business_shortcode, passkey)):
        raise ValueError('M-Pesa Daraja credentials are not configured')

    token_response = requests.get(
        f'{DARAJA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials',
        auth=HTTPBasicAuth(consumer_key, consumer_secret),
        timeout=20,
    )
    if not token_response.ok:
        detail = token_response.text.strip() or f'HTTP {token_response.status_code}'
        raise requests.HTTPError(f'Daraja token request failed: {detail}')
    try:
        access_token = token_response.json()['access_token']
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Daraja token response did not contain an access token') from error

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        f'{business_shortcode}{passkey}{timestamp}'.encode()
    ).decode()
    payload = {
        'BusinessShortCode': business_shortcode,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': int(float(amount)),
        'PartyA': phone,
        'PartyB': business_shortcode,
        'PhoneNumber': phone,
        'CallBackURL': callback_url,
        'AccountReference': account_reference,
        'TransactionDesc': description,
    }
    response = requests.post(
        f'{DARAJA_BASE_URL}/mpesa/stkpush/v1/processrequest',
        json=payload,
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=20,
    )
    if not response.ok:
        detail = response.text.strip() or f'HTTP {response.status_code}'
        raise requests.HTTPError(f'Daraja STK request failed: {detail}')
    try:
        return response.json()
    except ValueError as error:
        raise ValueError('Daraja STK response was not valid JSON') from error
