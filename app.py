import sys
import base64
import calendar
import os
import re
import secrets
from datetime import datetime, date, timedelta
from functools import wraps
from maintenance import is_maintenance_on, set_maintenance
from functools import wraps
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Only for http://localhost testing

try:
    import requests
    from requests.auth import HTTPBasicAuth
    from sqlalchemy import inspect
    from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
    from flask_sqlalchemy import SQLAlchemy
    from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
    from flask_bcrypt import Bcrypt
    from flask_dance.contrib.google import make_google_blueprint, google
except ModuleNotFoundError as e:
    missing = str(e).split("'")[1] if "'" in str(e) else str(e)
    print('\nERROR: Missing package:', missing)
    print(f'Run: pip install {missing}')
    sys.exit(1)

BUSINESS_SHORTCODE = "174379"
PASSKEY = "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919"
SUBSCRIPTION_CALLBACK_URL = "https://yourdomain.com/api/mpesa/callback/subscription"


def get_access_token():
    consumer_key = "YOUR_CONSUMER_KEY"
    consumer_secret = "YOUR_CONSUMER_SECRET"
    url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    r = requests.get(url, auth=(consumer_key, consumer_secret))
    return r.json()['access_token']

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bomamanager-secret-key-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bomamanager.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# GOOGLE OAUTH SETUP
blueprint = make_google_blueprint(
    client_id="697782513202-citmqbn4u1r5rovt3hmpphsjtpaaj5cj.apps.googleusercontent.com",
    client_secret="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",
    scope=["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"],
    redirect_to="google_login"
)
app.register_blueprint(blueprint, url_prefix="/login")

# M-PESA DARAJA CREDENTIALS
CONSUMER_KEY = 'LWkA9I10JShdwhEDHNsSRmKrHDhq4RTNaBET1T6pYJNmwAZR'
CONSUMER_SECRET = '1GsjhdGpk8IwxVQHfGTNLwJCgyrGGpXkSfCJPGGztwtE5NlyVepinfO9jdGWIojO'
BUSINESS_SHORTCODE = '174379'
PASSKEY = 'bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919'
CALLBACK_URL = 'https://tracks-dark-members-trackback.trycloudflare.com/api/mpesa/callback'

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def subscription_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and current_user.role == 'landlord' and not has_paid_subscription_access(current_user):
            flash('Your subscription is not active. Choose a plan to continue.', 'warning')
            return redirect(url_for('subscription_page'))
        return f(*args, **kwargs)
    return decorated_function


def has_paid_subscription_access(user):
    return (
        user.subscription_status == 'active'
        and user.subscription_expiry is not None
        and user.subscription_expiry > datetime.utcnow()
    )


@app.before_request
def check_subscription_global():
    if session.get('is_super_admin') or not current_user.is_authenticated:
        return None
    if current_user.role != 'landlord' or has_paid_subscription_access(current_user):
        return None
    allowed_endpoints = {
        'admin.admin_login',
        'admin.admin_dashboard',
        'admin.admin_logout',
        'admin.toggle_landlord',
        'home',
        'login',
        'register',
        'google_login',
        'choose_role',
        'set_role',
        'reset_password',
        'subscription_page',
        'pay_subscription',
        'bank_subscription_payment',
        'subscription_callback',
        'logout',
    }
    if request.endpoint in allowed_endpoints:
        return None
    return redirect(url_for('subscription_page'))
# ==================== MODELS ====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='pending')
    name = db.Column(db.String(100))
    contact_number = db.Column(db.String(30))
    must_change_password = db.Column(db.Boolean, default=False)
    password_reset_token = db.Column(db.String(255), nullable=True)
    password_reset_expires = db.Column(db.DateTime, nullable=True)
    landlord_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    tenants = db.relationship('User', backref=db.backref('landlord', remote_side=[id]), foreign_keys=[landlord_id])
    mpesa_till = db.Column(db.String(20), nullable=True)
    mpesa_type = db.Column(db.String(20), nullable=True)
    account_number = db.Column(db.String(100), nullable=True)
    bank_name = db.Column(db.String(100), nullable=True)
    is_landlord = db.Column(db.Boolean, default=False)
    subscription_status = db.Column(db.String(20), default='trial')
    subscription_plan = db.Column(db.String(20), default='basic')
    subscription_expiry = db.Column(db.DateTime, nullable=True)
    trial_ends_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=14))

    def has_active_subscription(self):
        if self.role == 'admin':
            return True
        if not self.is_landlord:
            return True
        if self.subscription_status == 'trial' and self.trial_ends_at and self.trial_ends_at > datetime.utcnow():
            return True
        if self.subscription_status == 'active' and self.subscription_expiry and self.subscription_expiry > datetime.utcnow():
            return True
        return False

    def can_add_more_rooms(self):
        if not self.has_active_subscription():
            return False
        if self.subscription_plan == 'pro':
            return True
        count = Room.query.join(Property).filter(Property.landlord_id == self.id).count()
        return count < 20

    def subscription_deadline(self):
        if self.role == 'admin':
            return None
        if self.is_landlord:
            if self.subscription_status == 'active' and self.subscription_expiry:
                return self.subscription_expiry
            if self.trial_ends_at:
                return self.trial_ends_at
        return None

    def subscription_countdown(self):
        return get_countdown_parts(self.subscription_deadline())

    def days_remaining(self):
        end_date = self.subscription_deadline()
        if not end_date:
            return 0
        delta = end_date - datetime.utcnow()
        return max(0, delta.days)

# Keep imports from admin.py attached to this instance when started with
# `python app.py`, where this module is named `__main__`.
sys.modules.setdefault('app', sys.modules[__name__])
from admin import admin_bp, admin_credentials_valid
app.register_blueprint(admin_bp)

class Property(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    property_type = db.Column(db.String(50), nullable=True)
    landlord_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    landlord = db.relationship('User', backref='properties')

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(20), nullable=False)
    room_type = db.Column(db.String(50), nullable=True)
    rent_amount = db.Column(db.Float, nullable=False)
    is_occupied = db.Column(db.Boolean, default=False)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    assigned_date = db.Column(db.Date, nullable=True)
    property = db.relationship('Property', backref='rooms')
    tenant = db.relationship('User', backref='room', foreign_keys=[tenant_id])

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    month = db.Column(db.String(20), nullable=False)
    date_paid = db.Column(db.DateTime, default=db.func.current_timestamp())
    mpesa_code = db.Column(db.String(50), nullable=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    room = db.relationship('Room', backref='payments')
    tenant = db.relationship('User', backref='payments', foreign_keys=[tenant_id])

class WaterBill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    units_used = db.Column(db.Float, nullable=False)
    rate_per_unit = db.Column(db.Float, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    month = db.Column(db.String(20), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    room = db.relationship('Room', backref='water_bills')
    tenant = db.relationship('User', backref='water_bills', foreign_keys=[tenant_id])
    __table_args__ = (db.UniqueConstraint('room_id', 'month', name='unique_water_bill_per_room_month'),)

class PendingBill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(250), nullable=True)
    month = db.Column(db.String(20), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    is_paid = db.Column(db.Boolean, default=False)
    room = db.relationship('Room', backref='pending_bills')
    tenant = db.relationship('User', backref='pending_bills', foreign_keys=[tenant_id])
    __table_args__ = (db.UniqueConstraint('room_id', 'month', 'title', name='unique_pending_bill_per_room_month_title'),)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_email = db.Column(db.String(150), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    target_email = db.Column(db.String(150), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

# ==================== HELPERS ====================
def get_access_token():
    api_url = "https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    response = requests.get(api_url, auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET))
    return response.json()['access_token']

def ensure_user_columns():
    columns = {column['name'] for column in inspect(db.engine).get_columns('user')}
    additions = {
        'must_change_password': 'BOOLEAN DEFAULT 0',
        'password_reset_token': 'VARCHAR(255)',
        'password_reset_expires': 'DATETIME',
        'mpesa_till': 'VARCHAR(20)',
        'mpesa_type': 'VARCHAR(20)',
        'account_number': 'VARCHAR(100)',
        'bank_name': 'VARCHAR(100)',
        'is_landlord': 'BOOLEAN DEFAULT 0',
        'subscription_status': "VARCHAR(20) DEFAULT 'trial'",
        'subscription_plan': "VARCHAR(20) DEFAULT 'basic'",
        'subscription_expiry': 'DATETIME',
        'trial_ends_at': 'DATETIME',
    }
    with db.engine.begin() as connection:
        for name, column_type in additions.items():
            if name not in columns:
                connection.exec_driver_sql(f'ALTER TABLE user ADD COLUMN {name} {column_type}')
        if 'trial_ends_at' in columns or 'trial_ends_at' in additions:
            connection.exec_driver_sql(
                'UPDATE user SET trial_ends_at = :trial_end '
                'WHERE trial_ends_at IS NULL AND is_landlord = 1',
                {'trial_end': datetime.utcnow() + timedelta(days=14)},
            )


def ensure_payout_columns():
    ensure_user_columns()


def ensure_property_columns():
    property_columns = {column['name'] for column in inspect(db.engine).get_columns('property')}
    room_columns = {column['name'] for column in inspect(db.engine).get_columns('room')}
    additions = {
        'property_type': 'VARCHAR(50)',
    }
    room_additions = {
        'room_type': 'VARCHAR(50)',
    }
    with db.engine.begin() as connection:
        for name, column_type in additions.items():
            if name not in property_columns:
                connection.exec_driver_sql(f'ALTER TABLE property ADD COLUMN {name} {column_type}')
        for name, column_type in room_additions.items():
            if name not in room_columns:
                connection.exec_driver_sql(f'ALTER TABLE room ADD COLUMN {name} {column_type}')


def ensure_pending_bill_table():
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    if 'pending_bill' not in existing_tables:
        db.create_all()


def generate_room_numbers(room_type, room_count, prefix=None, start_number=1):
    room_type = room_type or 'Room'
    prefix_map = {
        'Single Room': 'SR',
        'Bedsitter': 'BS',
        'One Bedroom': '1BR',
        'Two Bedroom': '2BR',
        'Three Bedroom': '3BR',
        'Studio': 'ST',
        'Apartment': 'APT',
        'Hostel': 'H',
        'Townhouse': 'TH',
        'Commercial Space': 'COM',
        'Air BnB': 'BnB'  
    }
    raw_prefix = (prefix or prefix_map.get(room_type, room_type[:2].upper())).strip().upper()
    start = max(1, int(start_number or 1))
    count = max(1, int(room_count or 1))
    room_numbers = []
    for index in range(start, start + count):
        room_numbers.append(f'{raw_prefix}-{index:02d}')
    return room_numbers


def format_phone(phone):
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith('0'):
        phone = '254' + phone[1:]
    if not phone.startswith('254'):
        phone = '254' + phone
    return phone


def get_countdown_parts(target_datetime):
    if not target_datetime:
        return {
            'days': 0,
            'hours': 0,
            'minutes': 0,
            'seconds': 0,
            'total_seconds': 0,
            'is_expired': True,
            'text': '00d 00h 00m 00s'
        }

    now = datetime.utcnow()
    delta = target_datetime - now
    total_seconds = max(0, int(delta.total_seconds()))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    return {
        'days': days,
        'hours': hours,
        'minutes': minutes,
        'seconds': seconds,
        'total_seconds': total_seconds,
        'is_expired': target_datetime <= now,
        'text': f'{days:02d}d {hours:02d}h {minutes:02d}m {seconds:02d}s'
    }


def get_billing_period(room, today=None):
    if not room.assigned_date:
        return None
    today = today or date.today()

    months_since_assignment = ((today.year - room.assigned_date.year) * 12 +
                               today.month - room.assigned_date.month)
    months_since_assignment = max(0, months_since_assignment)
    period_start = add_months(room.assigned_date, months_since_assignment)
    if period_start > today:
        period_start = add_months(room.assigned_date, months_since_assignment - 1)
    period_end = add_months(period_start, 1) - timedelta(days=1)
    due_at = datetime.combine(period_end, datetime.max.time())
    return {
        'key': period_start.isoformat(),
        'label': f'{period_start.strftime("%d %b %Y")} - {period_end.strftime("%d %b %Y")}',
        'end_date': period_end,
        'due_at': due_at
    }

def add_months(start_date, months):
    month_index = start_date.month - 1 + months
    year = start_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start_date.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def get_payment_summary(room, period_key):
    water_bill = WaterBill.query.filter_by(room_id=room.id, month=period_key).first()
    water_amount = water_bill.amount if water_bill else 0
    pending_bills = PendingBill.query.filter_by(room_id=room.id, month=period_key).all()
    pending_total = sum(b.amount for b in pending_bills)
    total_amount = room.rent_amount + water_amount + pending_total
    total_paid = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter_by(room_id=room.id, month=period_key).scalar()
    return {
        'water_bill': water_bill,
        'pending_bills': pending_bills,
        'pending_total': pending_total,
        'total_amount': total_amount,
        'total_paid': total_paid,
        'balance': max(0, total_amount - total_paid),
    }
def maintenance_check(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Allow admin to still access
        if is_maintenance_on() and not request.path.startswith('/admin'):
            return render_template('maintenance.html'), 503
        return f(*args, **kwargs)
    return decorated
# ==================== AUTH ROUTES ====================
@app.route('/admin/toggle-maintenance', methods=['POST'])
def toggle_maintenance():
    if session.get('role') != 'super_admin':
        return "Unauthorized", 403
    current = is_maintenance_on()
    set_maintenance(not current)
    return redirect(url_for('admin.admin_dashboard'))

@app.route('/admin/maintenance-status')
def maintenance_status():
    return {"maintenance": is_maintenance_on()}

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if admin_credentials_valid(email, password):
            logout_user()
            session['is_super_admin'] = True
            session['role'] = 'super_admin'
            session['admin_email'] = email
            return redirect(url_for('admin.admin_dashboard'))
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            if user.must_change_password:
                return redirect(url_for('reset_password'))
            if user.role == 'pending':
                return redirect(url_for('choose_role'))
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    landlords = User.query.filter_by(role='landlord').all()
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form['role']
        contact_number = request.form.get('contact_number', '').strip() or None
        landlord_id = request.form.get('landlord_id') if role == 'tenant' else None

        if not name:
            flash('Username is required')
            return render_template('register.html', landlords=landlords)

        if role == 'tenant' and not contact_number:
            flash('Tenant contact number is required')
            return render_template('register.html', landlords=landlords)

        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return render_template('register.html', landlords=landlords)

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(
            email=email,
            password=hashed_pw,
            role=role,
            is_landlord=(role == 'landlord'),
            landlord_id=landlord_id if landlord_id else None,
            name=name,
            contact_number=contact_number,
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Account created successfully!')
        return redirect(url_for('dashboard'))
    return render_template('register.html', landlords=landlords)

@app.route("/google_login")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Google login failed")
        return redirect(url_for("login"))

    user_info = resp.json()
    email = user_info["email"]
    name = user_info.get("name", "User")

    user = User.query.filter_by(email=email).first()

    if not user:
        user = User(
            email=email,
            name=name,
            password=bcrypt.generate_password_hash('google_oauth').decode('utf-8'),
            role='pending'
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for('choose_role'))

    login_user(user)
    if user.role == 'pending':
        return redirect(url_for('choose_role'))

    flash('Logged in with Google!')
    return redirect(url_for('dashboard'))

@app.route('/reset_password', methods=['GET', 'POST'])
@login_required
def reset_password():
    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if current_user.must_change_password and not bcrypt.check_password_hash(current_user.password, current_password):
            flash('The temporary password is incorrect. Please use the password provided by your landlord.')
            return render_template('reset_password.html')

        if len(new_password) < 6:
            flash('New password must be at least 6 characters long.')
            return render_template('reset_password.html')

        if new_password != confirm_password:
            flash('Passwords do not match.')
            return render_template('reset_password.html')

        current_user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
        current_user.must_change_password = False
        db.session.commit()
        flash('Password updated successfully!')
        return redirect(url_for('dashboard'))

    return render_template('reset_password.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    token_value = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            token_value = secrets.token_urlsafe(32)
            user.password_reset_token = token_value
            user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            flash(f'Password reset token created for {user.email}. Use the token below to reset your password.')
        else:
            flash('No account found with that email.')
    return render_template('forgot_password.html', token=token_value)

@app.route('/reset_password_token', methods=['GET', 'POST'])
def reset_password_token():
    token = request.args.get('token') or request.form.get('token', '').strip()
    if request.method == 'POST':
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not token:
            flash('A reset token is required.')
            return render_template('reset_password_token.html', token=token)
        if len(new_password) < 6:
            flash('New password must be at least 6 characters long.')
            return render_template('reset_password_token.html', token=token)
        if new_password != confirm_password:
            flash('Passwords do not match.')
            return render_template('reset_password_token.html', token=token)

        user = User.query.filter_by(password_reset_token=token).first()
        if not user or not user.password_reset_expires or user.password_reset_expires < datetime.utcnow():
            flash('This reset token is invalid or expired.')
            return render_template('reset_password_token.html', token=token)

        user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
        user.password_reset_token = None
        user.password_reset_expires = None
        user.must_change_password = False
        db.session.commit()
        flash('Password reset successful. Please login with your new password.')
        return redirect(url_for('login'))

    return render_template('reset_password_token.html', token=token)

@app.route('/settings', methods=['GET','POST'])
@login_required
def settings():
    if current_user.role != 'landlord':
        return "Access Denied"
    if request.method == 'POST':
        mpesa_till = request.form.get('mpesa_till', '').strip()
        mpesa_type = request.form.get('mpesa_type', '').strip()
        bank_name = request.form.get('bank_name', '').strip()
        account_number = request.form.get('account_number', '').strip()
        if not mpesa_till and not account_number:
            flash('Add an M-Pesa destination or a bank account.')
            return render_template('settings.html')
        if mpesa_till and (mpesa_type not in {'till', 'paybill', 'send_money', 'pochi'} or not mpesa_till.isdigit()):
            flash('Choose a valid M-Pesa option and enter its number.')
            return render_template('settings.html')
        if account_number and not bank_name:
            flash('Enter the bank name for the bank account.')
            return render_template('settings.html')
        current_user.mpesa_till = mpesa_till or None
        current_user.mpesa_type = mpesa_type if mpesa_till else None
        current_user.bank_name = bank_name or None
        current_user.account_number = account_number or None
        db.session.commit()
        flash('Payout settings saved!')
        return redirect(url_for('dashboard'))
    return render_template('settings.html')

@app.route("/choose_role")
@login_required
def choose_role():
    if current_user.role!= 'pending':
        return redirect(url_for('dashboard'))
    return render_template('choose_role.html')

@app.route("/set_role/<role>")
@login_required
def set_role(role):
    if role not in ['landlord', 'tenant']:
        flash('Invalid role')
        return redirect(url_for('choose_role'))
    current_user.role = role
    current_user.is_landlord = (role == 'landlord')
    db.session.commit()
    flash(f'Account setup complete! You are now a {role}.')
    return redirect(url_for('dashboard'))

# ==================== LANDLORD / TENANT LOGIC ====================
@app.route('/dashboard')
@login_required
@subscription_required
def dashboard():
    if current_user.role == 'pending':
        return redirect(url_for('choose_role'))
    if current_user.role == 'landlord':
        properties = Property.query.filter_by(landlord_id=current_user.id).all()
        tenants = User.query.filter_by(role='tenant', landlord_id=current_user.id).all()
        current_period_by_room = {room.id: get_billing_period(room) for prop in properties for room in prop.rooms}
        period_keys = [period['key'] for period in current_period_by_room.values() if period]
        water_bills = {bill.room_id: bill for bill in WaterBill.query.filter(WaterBill.month.in_(period_keys)).all()} if period_keys else {}
        pending_bills_by_room = {bill.room_id: bill for bill in PendingBill.query.filter(PendingBill.month.in_(period_keys)).all()} if period_keys else {}
        room_ids = [room.id for prop in properties for room in prop.rooms]
        payments = Payment.query.filter(Payment.room_id.in_(room_ids), Payment.month.in_(period_keys)).all() if room_ids and period_keys else []
        payments_by_room = {room_id: get_payment_summary(room, current_period_by_room[room_id]['key']) for room_id, room in [(room.id, room) for prop in properties for room in prop.rooms] if current_period_by_room[room_id]}
        current_month = datetime.now().strftime('%Y-%m')
        total_month_collection = db.session.query(db.func.sum(Payment.amount)).join(Room).join(Property).filter(Property.landlord_id == current_user.id, db.func.strftime('%Y-%m', Payment.date_paid) == current_month).scalar() or 0
        subscription_deadline = current_user.subscription_deadline()
        subscription_countdown = get_countdown_parts(subscription_deadline)
        return render_template('dashboard.html', properties=properties, tenants=tenants, room=None, payment_status=None, water_bills=water_bills, pending_bills_by_room=pending_bills_by_room, payments_by_room=payments_by_room, current_period_by_room=current_period_by_room, total_month_collection=total_month_collection, current_month_label=datetime.now().strftime('%B %Y'), subscription_deadline=subscription_deadline, subscription_countdown=subscription_countdown)
    else:
        properties = None
        room = None
        payment_status = "No room assigned yet"
        water_bill = None
        total_amount = 0
        total_paid = 0
        balance = 0
        paid = False
        current_period = None
        rent_due_countdown = None
        rent_due_target = None
        if current_user.room:
            room = current_user.room[0]
            current_period = get_billing_period(room)
            period_key = current_period['key'] if current_period else None
            summary = get_payment_summary(room, period_key) if period_key else {'water_bill': None, 'total_amount': 0, 'total_paid': 0, 'balance': 0}
            paid = summary['total_paid'] >= summary['total_amount'] if period_key else False
            water_bill = summary['water_bill']
            total_amount = summary['total_amount']
            total_paid = summary['total_paid']
            balance = summary['balance']
            payment_status = f"Room: {room.room_number} | Property: {room.property.name}"
            rent_due_target = current_period['due_at'] if current_period else None
            rent_due_countdown = get_countdown_parts(rent_due_target) if rent_due_target else None
    landlord = current_user.landlord if current_user.role == 'tenant' else None
    return render_template('dashboard.html', properties=properties, room=room, payment_status=payment_status, water_bill=water_bill, total_amount=total_amount, total_paid=total_paid, balance=balance, paid=paid, current_period=current_period, landlord=landlord, rent_due_target=rent_due_target, rent_due_countdown=rent_due_countdown)

@app.route('/update_contact', methods=['GET', 'POST'])
@login_required
def update_contact():
    if current_user.role not in ['landlord', 'tenant']:
        return "Access Denied"
    if request.method == 'POST':
        contact_number = request.form['contact_number'].strip()
        if current_user.role == 'tenant' and not contact_number:
            flash('Tenant contact number is required.')
            return render_template('update_contact.html')
        if contact_number and (not contact_number.replace('+', '').replace(' ', '').replace('-', '').isdigit() or len(contact_number.replace('+', '').replace(' ', '').replace('-', '')) < 9):
            flash('Enter a valid contact number.')
            return render_template('update_contact.html')
        current_user.contact_number = contact_number or None
        db.session.commit()
        flash('Contact number updated!')
        return redirect(url_for('dashboard'))
    return render_template('update_contact.html')

@app.route('/add_tenant', methods=['GET', 'POST'])
@login_required
def add_tenant():
    if current_user.role != 'landlord':
        flash('Only landlords can add tenants')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        name = request.form.get('name', '').strip()
        contact_number = request.form.get('contact_number', '').strip() or None

        if not email or not name:
            flash('Name and email are required.')
            return render_template('add_tenant.html')

        if contact_number and (not contact_number.replace('+', '').replace(' ', '').replace('-', '').isdigit() or len(contact_number.replace('+', '').replace(' ', '').replace('-', '')) < 9):
            flash('Enter a valid tenant contact number.')
            return render_template('add_tenant.html')

        if User.query.filter_by(email=email).first():
            flash('Email already exists.')
            return render_template('add_tenant.html')

        tenant = User(
            email=email,
            name=name,
            contact_number=contact_number,
            password=bcrypt.generate_password_hash('temp123').decode('utf-8'),
            role='tenant',
            landlord_id=current_user.id,
            is_landlord=False,
            must_change_password=True,
        )
        db.session.add(tenant)
        db.session.commit()
        flash(f'Tenant {name} added! Temporary password: temp123. They must change it on first login.')
        return redirect(url_for('dashboard'))

    return render_template('add_tenant.html')

@app.route('/mark_rent_paid/<int:room_id>', methods=['POST'])
@login_required
@subscription_required
def mark_rent_paid(room_id):
    if current_user.role != 'landlord':
        return "Access Denied"
    room = Room.query.get_or_404(room_id)
    if room.property.landlord_id != current_user.id:
        return "Access Denied"
    if not room.tenant_id:
        flash('Assign a tenant before marking rent as paid.')
        return redirect(url_for('dashboard'))

    current_period = get_billing_period(room)
    if not current_period:
        flash('Set an assignment date before marking rent as paid.')
        return redirect(url_for('dashboard'))
    period_key = current_period['key']
    summary = get_payment_summary(room, period_key)
    if summary['balance'] > 0:
        water_bill = WaterBill.query.filter_by(room_id=room.id, month=period_key).first()
        payment = Payment(
            amount=summary['balance'],
            month=period_key,
            room_id=room.id,
            tenant_id=room.tenant_id,
            mpesa_code='CASH'
        )
        db.session.add(payment)
        db.session.commit()
        flash(f'Room {room.room_number} marked as paid for {current_period["label"]}.')
    else:
        flash(f'Room {room.room_number} is already marked as paid for {current_period["label"]}.')
    return redirect(url_for('dashboard'))

@app.route('/mark_rent_unpaid/<int:room_id>', methods=['POST'])
@login_required
@subscription_required
def mark_rent_unpaid(room_id):
    if current_user.role != 'landlord':
        return "Access Denied"
    room = Room.query.get_or_404(room_id)
    if room.property.landlord_id != current_user.id:
        return "Access Denied"
    current_period = get_billing_period(room)
    if not current_period:
        flash('This room has no assignment date.')
        return redirect(url_for('dashboard'))
    payments = Payment.query.filter_by(room_id=room.id, month=current_period['key']).all()
    for payment in payments:
        db.session.delete(payment)
    if payments:
        db.session.commit()
    flash(f'Room {room.room_number} marked as not yet paid for {current_period["label"]}.')
    return redirect(url_for('dashboard'))

#... rest of your property / room / mpesa routes stay same...
@app.route('/add_property', methods=['GET', 'POST'])
@login_required
@subscription_required
def add_property():
    if current_user.role != 'landlord':
        return "Access Denied"

    property_types = ['Apartment', 'Bedsitter', 'Single Room', 'One Bedroom', 'Two Bedroom', 'Three Bedroom', 'Studio', 'Hostel', 'Townhouse', 'Commercial Space']
    room_types = ['Single Room', 'Bedsitter', 'One Bedroom', 'Two Bedroom', 'Three Bedroom', 'Studio', 'Apartment', 'Hostel', 'Townhouse', 'Commercial Space']

    if request.method == 'POST':
        property_name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        property_type = request.form.get('property_type', '').strip() or 'Apartment'
        room_type = request.form.get('room_type', '').strip() or property_type
        room_count = request.form.get('room_count', '1')
        room_prefix = request.form.get('room_prefix', '').strip()
        room_start = request.form.get('room_start', '1')
        rent_amount = request.form.get('rent_amount', '0')

        try:
            room_count = int(room_count)
        except (TypeError, ValueError):
            room_count = 1

        try:
            room_start = int(room_start)
        except (TypeError, ValueError):
            room_start = 1

        try:
            rent_amount = float(rent_amount)
        except (TypeError, ValueError):
            rent_amount = 0

        if not property_name or not location:
            flash('Property name and location are required.')
            return render_template('add_property.html', property_types=property_types, room_types=room_types)

        if room_count <= 0:
            flash('Select a valid number of rooms to add.')
            return render_template('add_property.html', property_types=property_types, room_types=room_types)

        if rent_amount <= 0:
            flash('Enter a valid rent amount for the rooms.')
            return render_template('add_property.html', property_types=property_types, room_types=room_types)

        prop = Property(name=property_name, location=location, property_type=property_type, landlord_id=current_user.id)
        db.session.add(prop)
        db.session.flush()

        room_numbers = generate_room_numbers(room_type, room_count, prefix=room_prefix, start_number=room_start)
        for room_number in room_numbers:
            room = Room(
                room_number=room_number,
                room_type=room_type,
                rent_amount=rent_amount,
                property_id=prop.id,
            )
            db.session.add(room)

        db.session.commit()
        flash(f'{room_count} {room_type} rooms added to {property_name}.')
        return redirect(url_for('dashboard'))

    return render_template('add_property.html', property_types=property_types, room_types=room_types)

@app.route('/edit_property/<int:prop_id>', methods=['GET', 'POST'])
@login_required
@subscription_required
def edit_property(prop_id):
    if current_user.role != 'landlord':
        return "Access Denied"
    prop = Property.query.filter_by(id=prop_id, landlord_id=current_user.id).first_or_404()
    if request.method == 'POST':
        prop.name = request.form['name']
        db.session.commit()
        flash('Property name updated!')
        return redirect(url_for('dashboard'))
    return render_template('add_property.html', prop=prop)

@app.route('/edit_room/<int:room_id>', methods=['GET', 'POST'])
@login_required
def edit_room(room_id):
    if current_user.role != 'landlord':
        return "Access Denied"
    room = Room.query.get_or_404(room_id)
    if room.property.landlord_id != current_user.id:
        return "Access Denied"
    if request.method == 'POST':
        try:
            rent_amount = float(request.form.get('rent', ''))
        except (TypeError, ValueError):
            flash('Enter a valid rent amount.')
            return render_template('add_room.html', prop=room.property, room=room)
        if rent_amount <= 0:
            flash('Rent amount must be greater than zero.')
            return render_template('add_room.html', prop=room.property, room=room)
        room.rent_amount = rent_amount
        db.session.commit()
        flash(f'Rent for Room {room.room_number} updated!')
        return redirect(url_for('dashboard'))
    return render_template('add_room.html', prop=room.property, room=room)

@app.route('/delete_property/<int:prop_id>', methods=['POST'])
@login_required
@subscription_required
def delete_property(prop_id):
    if current_user.role != 'landlord':
        return "Access Denied"
    prop = Property.query.filter_by(id=prop_id, landlord_id=current_user.id).first_or_404()
    for room in prop.rooms:
        Payment.query.filter_by(room_id=room.id).delete()
        WaterBill.query.filter_by(room_id=room.id).delete()
        db.session.delete(room)
    db.session.delete(prop)
    db.session.commit()
    flash('Property deleted!')
    return redirect(url_for('dashboard'))

@app.route('/add_room/<int:prop_id>', methods=['GET', 'POST'])
@login_required
@subscription_required
def add_room(prop_id):
    if current_user.role!= 'landlord': return "Access Denied"
    prop = Property.query.filter_by(id=prop_id, landlord_id=current_user.id).first_or_404()
    if request.method == 'POST':
        room = Room(room_number=request.form['room_number'], rent_amount=request.form['rent'], property_id=prop_id)
        db.session.add(room)
        db.session.commit()
        flash('Room Added!')
        return redirect(url_for('dashboard'))
    return render_template('add_room.html', prop=prop)

@app.route('/delete_room/<int:room_id>', methods=['POST'])
@login_required
@subscription_required
def delete_room(room_id):
    if current_user.role != 'landlord':
        return "Access Denied"
    room = Room.query.get_or_404(room_id)
    if room.property.landlord_id != current_user.id:
        return "Access Denied"
    Payment.query.filter_by(room_id=room.id).delete()
    WaterBill.query.filter_by(room_id=room.id).delete()
    db.session.delete(room)
    db.session.commit()
    flash('Room deleted!')
    return redirect(url_for('dashboard'))

@app.route('/water_bill/<int:room_id>', methods=['GET', 'POST'])
@login_required
def water_bill(room_id):
    if current_user.role != 'landlord':
        return "Access Denied"
    room = Room.query.get_or_404(room_id)
    if room.property.landlord_id != current_user.id:
        return "Access Denied"
    if not room.tenant:
        flash('Assign a tenant before adding a water bill.')
        return redirect(url_for('dashboard'))

    current_period = get_billing_period(room)
    if not current_period:
        flash('Set an assignment date before adding a water bill.')
        return redirect(url_for('dashboard'))
    period_key = current_period['key']
    bill = WaterBill.query.filter_by(room_id=room.id, month=period_key).first()
    if request.method == 'POST':
        units_used = float(request.form['units_used'])
        rate_per_unit = float(request.form['rate_per_unit'])
        if units_used < 0 or rate_per_unit < 0:
            flash('Water units and rate cannot be negative.')
            return render_template('water_bill.html', room=room, bill=bill, current_period=current_period)
        if bill:
            bill.units_used = units_used
            bill.rate_per_unit = rate_per_unit
            bill.amount = units_used * rate_per_unit
            bill.tenant_id = room.tenant_id
        else:
            bill = WaterBill(
                units_used=units_used,
                rate_per_unit=rate_per_unit,
                amount=units_used * rate_per_unit,
                month=period_key,
                room_id=room.id,
                tenant_id=room.tenant_id
            )
            db.session.add(bill)
        db.session.commit()
        flash('Water bill saved!')
        return redirect(url_for('dashboard'))
    return render_template('water_bill.html', room=room, bill=bill, current_period=current_period)

@app.route('/pending_bill/<int:room_id>', methods=['GET', 'POST'])
@login_required
@subscription_required
def pending_bill(room_id):
    if current_user.role != 'landlord':
        return "Access Denied"
    room = Room.query.get_or_404(room_id)
    if room.property.landlord_id != current_user.id:
        return "Access Denied"
    if not room.tenant:
        flash('Assign a tenant before adding a pending bill.')
        return redirect(url_for('dashboard'))

    current_period = get_billing_period(room)
    if not current_period:
        flash('Set an assignment date before adding a pending bill.')
        return redirect(url_for('dashboard'))

    period_key = current_period['key']
    bill = PendingBill.query.filter_by(room_id=room.id, month=period_key).first()

    if request.method == 'POST':
        title = request.form.get('title', '').strip() or 'Miscellaneous bill'
        amount = request.form.get('amount', '0').strip()
        note = request.form.get('note', '').strip()
        try:
            amount_value = float(amount)
        except (TypeError, ValueError):
            flash('Enter a valid amount for the pending bill.')
            return render_template('pending_bill.html', room=room, bill=bill, current_period=current_period)
        if amount_value < 0:
            flash('Pending bills cannot be negative.')
            return render_template('pending_bill.html', room=room, bill=bill, current_period=current_period)

        if bill:
            bill.title = title
            bill.amount = amount_value
            bill.note = note or None
            bill.tenant_id = room.tenant_id
        else:
            bill = PendingBill(
                title=title,
                amount=amount_value,
                note=note or None,
                month=period_key,
                room_id=room.id,
                tenant_id=room.tenant_id
            )
            db.session.add(bill)
        db.session.commit()
        flash('Pending bill saved successfully.')
        return redirect(url_for('dashboard'))

    return render_template('pending_bill.html', room=room, bill=bill, current_period=current_period)

@app.route('/assign_tenant/<int:room_id>', methods=['GET', 'POST'])
@login_required
@subscription_required
def assign_tenant(room_id):
    if current_user.role!= 'landlord': return "Access Denied"
    room = Room.query.get_or_404(room_id)
    if room.property.landlord_id != current_user.id:
        return "Access Denied"
    # Only show tenants linked to this landlord.
    tenants = User.query.filter_by(role='tenant', landlord_id=current_user.id).all()
    if request.method == 'POST':
        tenant_id = request.form['tenant_id']
        assigned_date = datetime.strptime(request.form['assigned_date'], '%Y-%m-%d').date()
        room.tenant_id = tenant_id
        room.is_occupied = True
        room.assigned_date = assigned_date
        db.session.commit()
        flash('Tenant Assigned!')
        return redirect(url_for('dashboard'))
    return render_template('assign_tenant.html', room=room, tenants=tenants, today=date.today().isoformat())

@app.route('/update_assignment_date/<int:room_id>', methods=['GET', 'POST'])
@login_required
@subscription_required
def update_assignment_date(room_id):
    if current_user.role != 'landlord':
        return "Access Denied"
    room = Room.query.get_or_404(room_id)
    if room.property.landlord_id != current_user.id:
        return "Access Denied"
    if not room.tenant_id:
        flash('Assign a tenant before setting an assignment date.')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        try:
            room.assigned_date = datetime.strptime(request.form['assigned_date'], '%Y-%m-%d').date()
        except (KeyError, ValueError):
            flash('Enter a valid assignment date.')
            return render_template('update_assignment_date.html', room=room)
        db.session.commit()
        flash(f'Assignment date for Room {room.room_number} updated.')
        return redirect(url_for('dashboard'))
    return render_template('update_assignment_date.html', room=room)

@app.route('/vacate_room/<int:room_id>')
@login_required
@subscription_required
def vacate_room(room_id):
    if current_user.role!= 'landlord': return "Access Denied"
    room = Room.query.get_or_404(room_id)
    room.tenant_id = None
    room.is_occupied = False
    room.assigned_date = None
    db.session.commit()
    flash('Room has been vacated!')
    return redirect(url_for('dashboard'))

@app.route('/stk_push/<int:room_id>', methods=['POST'])
@login_required
def stk_push(room_id):
    room = Room.query.get_or_404(room_id)
    if room.tenant_id != current_user.id:
        return "Access Denied"

    landlord = room.property.landlord
    if not landlord or not landlord.mpesa_till:
        flash('Your landlord has not set an M-Pesa destination yet.')
        return redirect(url_for('pay_rent', room_id=room_id))

    # Manual methods - no STK
    if landlord.mpesa_type in ['send_money', 'pochi', 'bank']:
        if landlord.mpesa_type == 'send_money':
            flash(f'Send Ksh {room.rent_amount} to {landlord.mpesa_till} ({landlord.name}) via M-Pesa > Send Money, then click "I Have Paid"')
        elif landlord.mpesa_type == 'pochi':
            flash(f'Send Ksh {room.rent_amount} to Pochi la Biashara number {landlord.mpesa_till}, then keep your confirmation message.')
        else:
            flash(f'Deposit to Bank: {landlord.bank_name} Acc: {landlord.account_number} Branch: {landlord.bank_branch if hasattr(landlord, "bank_branch") else ""}')
        return redirect(url_for('pay_rent', room_id=room_id))

    # For demo/sandbox - STK will always use YOUR paybill 174379 to simulate
    # In production, you would B2C the money to landlord after callback
    current_period = get_billing_period(room)
    if not current_period:
        flash('This room has no assignment date.')
        return redirect(url_for('dashboard'))
    
    summary = get_payment_summary(room, current_period['key'])
    
    try:
        requested_amount = float(request.form['amount'])
    except (KeyError, TypeError, ValueError):
        flash('Enter a valid payment amount.')
        return redirect(url_for('pay_rent', room_id=room_id))
    
    if requested_amount <= 0 or requested_amount > summary['balance']:
        flash(f'Enter an amount between Ksh 1 and Ksh {summary["balance"]:.2f}.')
        return redirect(url_for('pay_rent', room_id=room_id))

    raw_phone = request.form.get('phone', '')
    phone = format_phone(raw_phone)
    if len(phone) != 12:
        flash("Invalid phone number. Use 07XXXXXXXX")
        return redirect(url_for('pay_rent', room_id=room_id))

    # IMPORTANT: Password must use YOUR shortcode + YOUR passkey, not landlord's till
    access_token = get_access_token()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode((BUSINESS_SHORTCODE + PASSKEY + timestamp).encode()).decode('utf-8')

    # For Till vs Paybill
    transaction_type = "CustomerBuyGoodsOnline" if landlord.mpesa_type == 'till' else "CustomerPayBillOnline"
    
    payload = {
        "BusinessShortCode": BUSINESS_SHORTCODE,  # YOUR shortcode for STK
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": transaction_type,
        "Amount": int(requested_amount),
        "PartyA": phone,
        "PartyB": BUSINESS_SHORTCODE, # Money comes to YOU first in demo
        "PhoneNumber": phone,
        "CallBackURL": CALLBACK_URL,
        "AccountReference": f"Room{room.room_number}_Landlord{landlord.id}", # Track who it's for
        "TransactionDesc": f"Rent {room.property.name} for {landlord.name}"
    }
    
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.post("https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest", json=payload, headers=headers)
    data = response.json()
    print("STK Response:", data)

    if data.get('ResponseCode') == '0':
        flash(f"STK Push sent to {phone}. Check phone to pay Ksh {requested_amount}. Money will be forwarded to landlord's {landlord.mpesa_type}: {landlord.mpesa_till}")
    else:
        flash(f"STK failed: {data.get('errorMessage', data)}")
    
    return redirect(url_for('dashboard'))

@app.route('/api/mpesa/callback', methods=['POST'])
def mpesa_callback():
    data = request.get_json()
    print("M-PESA CALLBACK:", data)

    try:
        stk_callback = data['Body']['stkCallback']
        result_code = stk_callback['ResultCode']
        result_desc = stk_callback.get('ResultDesc', '')

        # 1. Payment failed / cancelled by user
        if result_code!= 0:
            print(f"STK Failed: Code {result_code} - {result_desc}")
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

        # 2. Payment success - parse metadata
        items = stk_callback['CallbackMetadata']['Item']
        metadata = {item['Name']: item.get('Value') for item in items}

        amount = metadata.get('Amount')
        mpesa_code = metadata.get('MpesaReceiptNumber')
        phone = metadata.get('PhoneNumber')
        account_ref = metadata.get('AccountReference', '') # e.g. RoomA1_Landlord5

        print(f"Received: {amount} | Code: {mpesa_code} | Ref: {account_ref}")

        # 3. Parse Room + Landlord from AccountReference
        # Supports both: "RoomA1" (old) and "RoomA1_Landlord5" (new)
        room_number = account_ref
        landlord_id_from_ref = None

        if "_Landlord" in account_ref:
            parts = account_ref.split("_Landlord")
            room_number = parts[0].replace("Room", "")
            try:
                landlord_id_from_ref = int(parts[1])
            except:
                landlord_id_from_ref = None
        elif account_ref.startswith("Room"):
            room_number = account_ref.replace("Room", "")

        room = Room.query.filter_by(room_number=room_number).first()

        if not room:
            print(f"ERROR: Room {room_number} not found for ref {account_ref}")
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

        # 4. Get billing period
        current_period = get_billing_period(room)
        if not current_period:
            print(f"No billing period for Room {room_number}")
            # Fallback to current month
            from datetime import datetime
            current_period = {'key': datetime.now().strftime("%B %Y")}

        month_key = current_period['key']

        # 5. Prevent double-save (M-Pesa can send callback twice)
        existing = Payment.query.filter_by(mpesa_code=mpesa_code).first()
        if existing:
            print(f"Duplicate callback ignored: {mpesa_code}")
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

        # 6. Save payment
        payment = Payment(
            amount=amount,
            month=month_key,
            room_id=room.id,
            tenant_id=room.tenant_id,
            mpesa_code=mpesa_code
        )
        db.session.add(payment)
        db.session.commit()

        # 7. SPLIT LOGIC - Who does this money belong to?
        landlord = room.property.landlord
        commission_rate = 0.05 # 5% - you keep this

        commission = round(amount * commission_rate, 2)
        to_landlord = round(amount - commission, 2)

        print(f"✅ Payment saved: Room {room_number} | {amount} | {mpesa_code}")
        print(f" → Belongs to Landlord {landlord.email} (ID: {landlord.id})")
        print(f" → Landlord Till: {landlord.mpesa_till} ({landlord.mpesa_type})")
        print(f" → SPLIT: You keep Ksh {commission} | Send Ksh {to_landlord} to landlord")
        print(f" → DISBURSEMENT NEEDED: B2C to {landlord.mpesa_till} - Ksh {to_landlord}")

        # TODO (for real production): Trigger B2C payout here
        # b2c_payout(phone=landlord.mpesa_till, amount=to_landlord, reference=mpesa_code)

    except Exception as e:
        print("Callback Error:", e)
        import traceback
        traceback.print_exc()
        # Always return Accepted, otherwise Safaricom will keep retrying
        db.session.rollback()

    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})
@app.route('/pay_rent/<int:room_id>', methods=['GET'])
@login_required
def pay_rent(room_id):
    if current_user.role!= 'tenant': return "Access Denied"
    room = Room.query.get_or_404(room_id)
    current_period = get_billing_period(room)
    if not current_period:
        flash('This room has no assignment date.')
        return redirect(url_for('dashboard'))
    period_key = current_period['key']
    summary = get_payment_summary(room, period_key)
    return render_template('pay_rent.html', room=room, landlord=room.property.landlord, water_bill=summary['water_bill'], total_amount=summary['total_amount'], total_paid=summary['total_paid'], balance=summary['balance'], paid=summary['balance'] == 0, current_period=current_period)

@app.route('/payment_history')
@login_required
def payment_history():
    if current_user.role == 'landlord':
        properties = Property.query.filter_by(landlord_id=current_user.id).all()
        room_ids = [r.id for p in properties for r in p.rooms]
        payments = Payment.query.filter(Payment.room_id.in_(room_ids)).order_by(Payment.date_paid.desc()).all() if room_ids else []
        payment_rows = []
        monthly_collections = {}
        for payment in payments:
            water_bill = WaterBill.query.filter_by(room_id=payment.room_id, month=payment.month).first()
            rent_amount = payment.room.rent_amount
            water_amount = water_bill.amount if water_bill else 0
            row = {
                'payment': payment,
                'rent_amount': rent_amount,
                'water_amount': water_amount,
                'total_amount': payment.amount,
                'payment_method': 'Cash' if payment.mpesa_code == 'CASH' else 'M-Pesa'
            }
            payment_rows.append(row)
            monthly_collections[payment.month] = monthly_collections.get(payment.month, 0) + payment.amount
        return render_template('payment_history.html', payments=payments, payment_rows=payment_rows, monthly_collections=monthly_collections)
    else:
        payments = Payment.query.filter_by(tenant_id=current_user.id).order_by(Payment.date_paid.desc()).all()
    return render_template('payment_history.html', payments=payments)
@app.route('/subscription')
@login_required
def subscription_page():
    return render_template('subsription.html',
                           user=current_user,
                           days_left=current_user.days_remaining())

@app.route('/pay-subscription', methods=['POST'])
@login_required
def pay_subscription():
    plan = request.form.get('plan', 'basic')
    if plan not in {'basic', 'pro'}:
        plan = 'basic'
    phone = (request.form.get('phone') or '').strip()

    if not phone:
        flash('Enter your phone number to pay for the subscription.', 'danger')
        return redirect(url_for('subscription_page'))

    if phone.startswith('0'):
        phone = '254' + phone[1:]

    if not phone.startswith('254'):
        phone = '254' + phone

    if len(phone) != 12:
        flash('Use a valid phone number in the format 07XXXXXXXX or 2547XXXXXXXX.', 'danger')
        return redirect(url_for('subscription_page'))

    amount = 500 if plan == 'basic' else 1000

    session['pending_plan'] = plan
    session['pending_landlord_id'] = current_user.id

    access_token = get_access_token()
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode((BUSINESS_SHORTCODE + PASSKEY + timestamp).encode()).decode('utf-8')

    payload = {
        "BusinessShortCode": BUSINESS_SHORTCODE,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": BUSINESS_SHORTCODE,
        "PhoneNumber": phone,
        "CallBackURL": SUBSCRIPTION_CALLBACK_URL,
        "AccountReference": f"SUB_Landlord{current_user.id}_{plan}",
        "TransactionDesc": f"BomaManager {plan} Subscription"
    }

    url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        response_data = response.json()
    except (requests.RequestException, ValueError) as error:
        print(f'Subscription M-Pesa request error: {error}')
        flash('M-Pesa is temporarily unavailable. Please try again or use bank transfer.', 'danger')
        return redirect(url_for('subscription_page'))

    print('Subscription STK response:', response_data)
    if response_data.get('ResponseCode') == '0':
        flash(f'STK Push sent to {phone} for Ksh {amount}. Enter your M-Pesa PIN.', 'success')
    else:
        message = response_data.get('errorMessage') or response_data.get('ResponseDescription') or 'M-Pesa rejected the request.'
        flash(f'M-Pesa payment could not start: {message}', 'danger')
    return redirect(url_for('subscription_page'))

@app.route('/bank-subscription-payment', methods=['POST'])
@login_required
def bank_subscription_payment():
    plan = request.form.get('plan', 'basic')
    if plan not in {'basic', 'pro'}:
        plan = 'basic'
    reference = (request.form.get('reference') or '').strip()
    if not reference:
        flash('Enter the bank transfer reference so we can confirm your payment.', 'danger')
        return redirect(url_for('subscription_page'))

    session['pending_plan'] = plan
    session['bank_payment_reference'] = reference
    session['pending_landlord_id'] = current_user.id
    flash('Bank payment details received. Your subscription will activate after the transfer is confirmed.', 'success')
    return redirect(url_for('subscription_page'))

@app.route('/api/mpesa/callback/subscription', methods=['POST'])
def subscription_callback():
    data = request.get_json()
    print("SUB CALLBACK:", data)
    try:
        cb = data['Body']['stkCallback']
        if cb['ResultCode'] != 0:
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})

        meta = {i['Name']: i.get('Value') for i in cb['CallbackMetadata']['Item']}
        account_ref = meta.get('AccountReference', '')

        parts = account_ref.split('_')
        landlord_id = None
        plan = 'basic'

        if len(parts) >= 3 and parts[0] == 'SUB' and parts[1].startswith('Landlord'):
            landlord_id = int(re.sub(r'[^0-9]', '', parts[1]))
            plan = parts[2]

        if landlord_id is None:
            landlord_id = session.get('pending_landlord_id')

        landlord = User.query.get(landlord_id)
        if landlord:
            landlord.subscription_status = 'active'
            landlord.subscription_plan = plan
            landlord.subscription_expiry = datetime.utcnow() + timedelta(days=30)
            db.session.commit()
            print(f"✅ Subscription activated: Landlord {landlord_id} | Plan {plan} | 30 days")

    except Exception as e:
        print(f"Sub callback error: {e}")
        import traceback
        traceback.print_exc()

    return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"})
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_user_columns()
        ensure_payout_columns()
        ensure_property_columns()
        ensure_pending_bill_table()
    app.run(debug=True)