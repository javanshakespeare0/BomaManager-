import base64
import os
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth


DARAJA_ENV = os.getenv('DARAJA_ENV', 'sandbox').lower()
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


def stk_push2(phone, amount, account_reference='BomaManager', description='Rent payment'):
    """Send an STK Push and return Daraja's decoded response."""
    token_response = requests.get(
        f'{DARAJA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials',
        auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET),
        timeout=20,
    )
    token_response.raise_for_status()
    access_token = token_response.json()['access_token']

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        f'{BUSINESS_SHORTCODE}{PASSKEY}{timestamp}'.encode()
    ).decode()
    payload = {
        'BusinessShortCode': BUSINESS_SHORTCODE,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': int(float(amount)),
        'PartyA': phone,
        'PartyB': BUSINESS_SHORTCODE,
        'PhoneNumber': phone,
        'CallBackURL': CALLBACK_URL,
        'AccountReference': account_reference,
        'TransactionDesc': description,
    }
    response = requests.post(
        f'{DARAJA_BASE_URL}/mpesa/stkpush/v1/processrequest',
        json=payload,
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()
