import base64
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import requests
from requests.auth import HTTPBasicAuth


DARAJA_APP_ENV = (
    os.getenv('APP_ENV') or os.getenv('FLASK_ENV') or 'development'
).strip().lower()
DARAJA_ENV = os.getenv(
    'DARAJA_ENV',
    os.getenv(
        'MPESA_ENV',
        'production' if DARAJA_APP_ENV == 'production' else 'sandbox',
    ),
).strip().lower()
if DARAJA_ENV not in {'sandbox', 'production'}:
    raise ValueError('DARAJA_ENV must be either "sandbox" or "production"')
DARAJA_BASE_URL = (
    'https://api.safaricom.co.ke'
    if DARAJA_ENV == 'production'
    else 'https://sandbox.safaricom.co.ke'
)
CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY', '')
CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET', '')
BUSINESS_SHORTCODE = os.getenv(
    'MPESA_BUSINESS_SHORTCODE',
    '174379' if DARAJA_ENV == 'sandbox' else '',
)
PASSKEY = os.getenv('MPESA_PASSKEY', '')
CALLBACK_URL = os.getenv(
    'MPESA_CALLBACK_URL',
    'https://your-public-domain.example/api/mpesa/callback',
)


def _whole_shilling_amount(amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('M-Pesa amount must be a positive whole number of shillings')
    if not value.is_finite() or value <= 0 or value != value.to_integral_value():
        raise ValueError('M-Pesa amount must be a positive whole number of shillings')
    return int(value)


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
    """Send an STK push and return Daraja's decoded response."""
    consumer_key = consumer_key or CONSUMER_KEY
    consumer_secret = consumer_secret or CONSUMER_SECRET
    business_shortcode = business_shortcode or BUSINESS_SHORTCODE
    passkey = passkey or PASSKEY
    callback_url = callback_url or CALLBACK_URL
    if not all((consumer_key, consumer_secret, business_shortcode, passkey)):
        raise ValueError('M-Pesa Daraja credentials are not configured')
    if not isinstance(phone, str) or not re.fullmatch(r'254(?:7|1)\d{8}', phone):
        raise ValueError('M-Pesa phone number must use the 2547XXXXXXXX or 2541XXXXXXXX format')
    if not isinstance(callback_url, str) or not callback_url.startswith('https://'):
        raise ValueError('M-Pesa callback URL must use HTTPS')
    amount = _whole_shilling_amount(amount)

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
    if not isinstance(access_token, str) or not access_token.strip():
        raise ValueError('Daraja token response did not contain an access token')

    timestamp = datetime.now(timezone(timedelta(hours=3))).strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        f'{business_shortcode}{passkey}{timestamp}'.encode()
    ).decode()
    payload = {
        'BusinessShortCode': business_shortcode,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': amount,
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
        result = response.json()
    except ValueError as error:
        raise ValueError('Daraja STK response was not valid JSON') from error
    if not isinstance(result, dict):
        raise ValueError('Daraja STK response must be a JSON object')
    return result
