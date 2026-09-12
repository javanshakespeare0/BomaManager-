from datetime import datetime, timedelta
from app import app, db, User, bcrypt

app.app_context().push()
db.create_all()
email = 'countdown_ok@test.com'
user = User.query.filter_by(email=email).first()
if not user:
    user = User(
        email=email,
        password=bcrypt.generate_password_hash('pass').decode(),
        role='landlord',
        is_landlord=True,
        name='Landlord Countdown',
        subscription_status='active',
        subscription_plan='basic',
        subscription_expiry=datetime.utcnow() + timedelta(days=30),
    )
    db.session.add(user)
    db.session.commit()

client = app.test_client()
with client.session_transaction() as sess:
    sess['_user_id'] = str(user.id)
    sess['_fresh'] = True

resp = client.get('/dashboard')
print('status', resp.status_code)
text = resp.get_data(as_text=True).lower()
print('has_countdown_banner', 'countdown' in text)
print('has_subscription', 'subscription countdown' in text)
print('has_days', 'days' in text)
print('title_ok', 'welcome' in text)
