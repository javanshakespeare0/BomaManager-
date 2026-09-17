from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import secrets
from sqlalchemy import or_

admin_bp = Blueprint('admin', __name__)

ADMIN_EMAIL = "javanshakespeare0@gmail.com"
ADMIN_PASSWORD_HASH = generate_password_hash("@tha_admin#")

def admin_credentials_valid(email, password):
    return email == ADMIN_EMAIL and check_password_hash(ADMIN_PASSWORD_HASH, password)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'is_super_admin' not in session:
            return redirect(url_for('admin.admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def record_admin_action(db, AuditLog, action, target_email):
    db.session.add(AuditLog(
        admin_email=session.get('admin_email', 'super admin'),
        action=action,
        target_email=target_email,
    ))

@admin_bp.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if admin_credentials_valid(email, password):
            session['is_super_admin'] = True
            session['admin_email'] = email
            return redirect(url_for('admin.admin_dashboard'))
        else:
            flash('Wrong admin email or password', 'error')
    return render_template('admin_login.html')

@admin_bp.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    from app import AuditLog, Payment, Property, Room, User, db
    from maintenance import is_maintenance_on

    search = request.args.get('q', '').strip()
    status = request.args.get('status', 'all').strip().lower()
    landlord_query = User.query.filter_by(role='landlord')
    if search:
        landlord_query = landlord_query.filter(or_(User.name.ilike(f'%{search}%'), User.email.ilike(f'%{search}%')))
    if status in {'active', 'expired', 'trial'}:
        landlord_query = landlord_query.filter_by(subscription_status=status)
    landlords = landlord_query.order_by(User.id.desc()).all()
    landlord_rows = []
    for landlord in landlords:
        properties = Property.query.filter_by(landlord_id=landlord.id).all()
        rooms = [room for property in properties for room in property.rooms]
        landlord_rows.append({
            'user': landlord,
            'property_count': len(properties),
            'room_count': len(rooms),
            'occupied_count': sum(room.is_occupied for room in rooms),
            'tenant_count': User.query.filter_by(landlord_id=landlord.id, role='tenant').count(),
        })

    total_properties = Property.query.count()
    total_rooms = Room.query.count()
    total_tenants = User.query.filter_by(role='tenant').count()
    occupied_rooms = Room.query.filter_by(is_occupied=True).count()
    recent_payments = Payment.query.order_by(Payment.date_paid.desc()).limit(20).all()
    audit_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(12).all()
    maintenance_state = is_maintenance_on()

    return render_template('admin_dashboard.html',
                         total_landlords=len(landlords),
                         total_properties=total_properties,
                         total_rooms=total_rooms,
                         total_tenants=total_tenants,
                         occupied_rooms=occupied_rooms,
                         landlord_rows=landlord_rows,
                         recent_payments=recent_payments,
                         audit_logs=audit_logs,
                         search=search,
                         status=status,
                         maintenance=maintenance_state)

@admin_bp.route('/admin/landlord/<int:user_id>')
@admin_required
def landlord_detail(user_id):
    from app import Payment, Property, Room, User

    landlord = User.query.filter_by(id=user_id, role='landlord').first_or_404()
    properties = Property.query.filter_by(landlord_id=landlord.id).order_by(Property.name).all()
    rooms = Room.query.join(Property).filter(Property.landlord_id == landlord.id).order_by(Room.room_number).all()
    tenants = User.query.filter_by(landlord_id=landlord.id, role='tenant').order_by(User.name, User.email).all()
    payments = Payment.query.join(Room).join(Property).filter(
        Property.landlord_id == landlord.id
    ).order_by(Payment.date_paid.desc()).limit(30).all()

    return render_template(
        'admin_landlord.html',
        landlord=landlord,
        properties=properties,
        rooms=rooms,
        tenants=tenants,
        payments=payments,
        occupied_rooms=sum(room.is_occupied for room in rooms),
    )

@admin_bp.route('/admin/logout')
def admin_logout():
    session.pop('is_super_admin', None)
    session.pop('admin_email', None)
    return redirect(url_for('admin.admin_login'))

@admin_bp.route('/admin/landlord/<int:user_id>/activate', methods=['POST'])
@admin_required
def activate_landlord(user_id):
    from app import AuditLog, User, db

    landlord = User.query.filter_by(id=user_id, role='landlord').first_or_404()
    plan = request.form.get('plan', 'basic')
    if plan not in {'basic', 'pro'}:
        plan = 'basic'
    try:
        days = max(1, min(366, int(request.form.get('days', 30))))
    except (TypeError, ValueError):
        days = 30

    landlord.subscription_status = 'active'
    landlord.subscription_plan = plan
    landlord.subscription_expiry = datetime.utcnow() + timedelta(days=days)
    record_admin_action(db, AuditLog, f'Activated {plan} plan for {days} days', landlord.email)
    db.session.commit()
    flash(f'{landlord.email} activated on the {plan} plan for {days} days.', 'success')
    return redirect(request.form.get('next') or url_for('admin.landlord_detail', user_id=landlord.id))

@admin_bp.route('/admin/landlord/<int:user_id>/deactivate', methods=['POST'])
@admin_required
def deactivate_landlord(user_id):
    from app import AuditLog, User, db

    landlord = User.query.filter_by(id=user_id, role='landlord').first_or_404()
    landlord.subscription_status = 'expired'
    landlord.subscription_expiry = datetime.utcnow()
    record_admin_action(db, AuditLog, 'Deactivated subscription', landlord.email)
    db.session.commit()
    flash(f'{landlord.email} subscription deactivated.', 'success')
    return redirect(request.form.get('next') or url_for('admin.landlord_detail', user_id=landlord.id))

@admin_bp.route('/admin/toggle-landlord/<int:user_id>', methods=['POST'])
@admin_required
def toggle_landlord(user_id):
    from app import AuditLog, User, db

    user = User.query.filter_by(id=user_id, role='landlord').first_or_404()
    if user.subscription_status == 'active':
        user.subscription_status = 'expired'
        user.subscription_expiry = datetime.utcnow()
        message = f'{user.email} subscription deactivated.'
        action = 'Deactivated subscription'
    else:
        user.subscription_status = 'active'
        user.subscription_plan = user.subscription_plan if user.subscription_plan in {'basic', 'pro'} else 'basic'
        user.subscription_expiry = datetime.utcnow() + timedelta(days=30)
        message = f'{user.email} subscription activated for 30 days.'
        action = 'Activated basic plan for 30 days'
    record_admin_action(db, AuditLog, action, user.email)
    db.session.commit()
    flash(message, 'success')
    return redirect(request.form.get('next') or url_for('admin.admin_dashboard'))

@admin_bp.route('/admin/landlord/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def reset_landlord_password(user_id):
    from app import AuditLog, User, bcrypt, db

    landlord = User.query.filter_by(id=user_id, role='landlord').first_or_404()
    temporary_password = secrets.token_urlsafe(9)
    landlord.password = bcrypt.generate_password_hash(temporary_password).decode('utf-8')
    landlord.must_change_password = True
    record_admin_action(db, AuditLog, 'Generated temporary password', landlord.email)
    db.session.commit()
    flash(f'Temporary password for {landlord.email}: {temporary_password}', 'warning')
    return redirect(url_for('admin.admin_dashboard'))

@admin_bp.route('/admin/landlord/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_landlord(user_id):
    from app import AuditLog, Payment, PendingBill, Property, Room, User, WaterBill, db

    landlord = User.query.filter_by(id=user_id, role='landlord').first_or_404()
    properties = Property.query.filter_by(landlord_id=landlord.id).all()
    room_ids = [room.id for property in properties for room in property.rooms]
    tenant_ids = [tenant.id for tenant in User.query.filter_by(landlord_id=landlord.id).all()]

    if room_ids:
        Payment.query.filter(Payment.room_id.in_(room_ids)).delete(synchronize_session=False)
        WaterBill.query.filter(WaterBill.room_id.in_(room_ids)).delete(synchronize_session=False)
        PendingBill.query.filter(PendingBill.room_id.in_(room_ids)).delete(synchronize_session=False)
        Room.query.filter(Room.id.in_(room_ids)).delete(synchronize_session=False)
    if tenant_ids:
        User.query.filter(User.id.in_(tenant_ids)).delete(synchronize_session=False)
    Property.query.filter_by(landlord_id=landlord.id).delete(synchronize_session=False)
    record_admin_action(db, AuditLog, 'Removed landlord and related data', landlord.email)
    db.session.delete(landlord)
    db.session.commit()

    flash(f'{landlord.email} and their landlord account data were removed.', 'success')
    return redirect(url_for('admin.admin_dashboard'))