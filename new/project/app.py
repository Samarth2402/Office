from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash, session
import json
import os
import re
import hashlib
import hmac
import smtplib
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from pdf_generator import generate_pdf
import uuid
from collections import defaultdict
from functools import wraps

try:
    import requests as req_lib
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

app = Flask(__name__)
app.secret_key = 'isoftrend_secret_key_2024_auth'

# ---- AUTH CONFIG ----
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_USER = 'isoftrendsystem@gmail.com'   # Gmail account that owns the App Password
SMTP_PASS = 'xbivwgvsffgaxqci'            # Gmail App Password
SMTP_FROM = 'iSoftrend System <isoftrendsystem@gmail.com>'

# OTP store: {email: {otp, expires, verified}}
_otp_store = {}

USERS_FILE = 'data/users.json'

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return []

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def find_user_by_email(email):
    for u in load_users():
        if u['email'].lower() == email.lower():
            return u
    return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            flash('Access denied. Admin only.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def generate_otp():
    import random
    return str(random.randint(100000, 999999))

def send_otp_email(to_email, otp):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'iSoftrend - Your OTP for Password Reset'
        msg['From'] = SMTP_FROM
        msg['To'] = to_email
        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#eef2f7;padding:30px;">
        <div style="max-width:500px;margin:auto;background:#fff;border-radius:12px;padding:32px;box-shadow:0 4px 20px rgba(0,0,0,.08);">
          <h2 style="color:#17284e;margin-bottom:8px;">Password Reset OTP</h2>
          <p style="color:#60708f;margin-bottom:24px;">Use the OTP below to reset your iSoftrend password. It expires in <strong>10 minutes</strong>.</p>
          <div style="text-align:center;margin:28px 0;">
            <span style="display:inline-block;background:#f0f7ff;border:2px dashed #2563eb;border-radius:12px;padding:18px 40px;font-size:36px;font-weight:900;letter-spacing:10px;color:#1d4ed8;">{otp}</span>
          </div>
          <p style="font-size:12px;color:#8a99b5;text-align:center;">Do not share this OTP with anyone. If you did not request this, please ignore.</p>
        </div>
        </body></html>"""
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

DATA_DIR = 'data'
UPLOAD_DIR = 'static/uploads/signatures'
LOGO_UPLOAD_DIR = 'static/uploads'

# ---- Fixed company identity (NOT editable via UI) ----
FIXED_COMPANY = {
    'company_name': 'iSoftrend System',
    'address': '615 - Shilp Arcade, Nr. Naroda-Dehgam Bridge, SP Ring Road, Hanspura, Ahmedabad - 382330',
    'state': 'Gujarat',
    'state_code': '24',
    'gstin': '24EFSPM5752Q1ZF',
    'phone': '+91 7984823208',
    'email': 'isoftrendsystem@gmail.com',
    'website': 'www.isoftrendsystem.in',
}

# ---- Default bank details ----
DEFAULT_BANK = {
    'bank_name': 'AXIS BANK LTD.',
    'account_number': '922020053137516',
    'account_name': 'ISOFTREND SYSTEM',
    'branch': 'RAKHIAL GJ, AHMEDABAD - 380023',
    'ifsc': 'UTIB0004021',
    'upi': '7984823208@axisbank',
}

DEFAULT_TERMS = (
    'The complete design and delivery process for the Logo, Letterhead, and Visiting Card will require '
    'approximately 6-7 working days from the date of confirmation and content approval.\n'
    'This includes concept creation, design revisions, and final file delivery in all required formats.\n\n'
    'If you require a GST invoice, an additional 18% will be charged on the quoted amount.'
)

PAYMENT_TERMS_DAYS = {
    'due_on_receipt': 0,
    'net_15': 15,
    'net_30': 30,
    'net_40': 40,
    'net_60': 60,
}

VALID_PAYMENT_STATUS = {'unpaid', 'partial', 'paid'}


def calculate_due_date(issue_date, payment_terms):
    """Return due date (YYYY-MM-DD) from issue_date and payment terms key."""
    try:
        base = datetime.strptime(issue_date, '%Y-%m-%d')
    except Exception:
        base = datetime.now()
    days = PAYMENT_TERMS_DAYS.get(payment_terms, 0)
    return (base + timedelta(days=days)).strftime('%Y-%m-%d')

# ---- Indian GST state codes ----
GST_STATE_CODES = {
    '01': 'Jammu and Kashmir', '02': 'Himachal Pradesh', '03': 'Punjab',
    '04': 'Chandigarh', '05': 'Uttarakhand', '06': 'Haryana', '07': 'Delhi',
    '08': 'Rajasthan', '09': 'Uttar Pradesh', '10': 'Bihar', '11': 'Sikkim',
    '12': 'Arunachal Pradesh', '13': 'Nagaland', '14': 'Manipur',
    '15': 'Mizoram', '16': 'Tripura', '17': 'Meghalaya', '18': 'Assam',
    '19': 'West Bengal', '20': 'Jharkhand', '21': 'Odisha', '22': 'Chhattisgarh',
    '23': 'Madhya Pradesh', '24': 'Gujarat', '25': 'Daman and Diu',
    '26': 'Dadra and Nagar Haveli', '27': 'Maharashtra', '28': 'Andhra Pradesh (Old)',
    '29': 'Karnataka', '30': 'Goa', '31': 'Lakshadweep', '32': 'Kerala',
    '33': 'Tamil Nadu', '34': 'Puducherry', '35': 'Andaman and Nicobar',
    '36': 'Telangana', '37': 'Andhra Pradesh',
}

# ---- Data helpers ----

def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return []

def save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def load_settings():
    path = os.path.join(DATA_DIR, 'settings.json')
    s = {}
    if os.path.exists(path):
        with open(path, 'r') as f:
            s = json.load(f)
    # Always apply fixed company details (cannot be overridden)
    s.update(FIXED_COMPANY)
    # Apply default bank details for any missing keys
    for k, v in DEFAULT_BANK.items():
        if not s.get(k):
            s[k] = v
    if not s.get('terms'):
        s['terms'] = DEFAULT_TERMS
    if not s.get('signature'):
        s['signature'] = 'default_sign.png'
    return s

def save_settings(settings_data):
    path = os.path.join(DATA_DIR, 'settings.json')
    existing = {}
    if os.path.exists(path):
        with open(path, 'r') as f:
            existing = json.load(f)
    existing.update(settings_data)
    # Never persist fixed company fields
    for key in FIXED_COMPANY:
        existing.pop(key, None)
    with open(path, 'w') as f:
        json.dump(existing, f, indent=2)

def peek_next_number(doc_type):
    """Return next number WITHOUT incrementing counter (safe for display)."""
    counters_path = os.path.join(DATA_DIR, 'counters.json')
    if os.path.exists(counters_path):
        with open(counters_path, 'r') as f:
            counters = json.load(f)
    else:
        counters = {'quotation': 260669, 'proforma': 260389, 'invoice': 2025100}
    prefix_map = {'quotation': 'QUO', 'proforma': 'ISS', 'invoice': 'INV'}
    num = counters.get(doc_type, 1000) + 1
    return f"{prefix_map.get(doc_type, 'DOC')}{num}"

def get_next_number(doc_type):
    """Increment counter and return next document number."""
    counters_path = os.path.join(DATA_DIR, 'counters.json')
    if os.path.exists(counters_path):
        with open(counters_path, 'r') as f:
            counters = json.load(f)
    else:
        counters = {'quotation': 260669, 'proforma': 260389, 'invoice': 2025100}
    prefix_map = {'quotation': 'QUO', 'proforma': 'ISS', 'invoice': 'INV'}
    counters[doc_type] = counters.get(doc_type, 1000) + 1
    num = counters[doc_type]
    with open(counters_path, 'w') as f:
        json.dump(counters, f, indent=2)
    return f"{prefix_map.get(doc_type, 'DOC')}{num}"

def get_monthly_data(invoices):
    monthly = defaultdict(lambda: {'paid': 0, 'unpaid': 0, 'total': 0})
    for inv in invoices:
        try:
            d = datetime.strptime(inv.get('date', ''), '%Y-%m-%d')
            key = d.strftime('%b %Y')
            total = inv.get('total', 0)
            monthly[key]['total'] += total
            if inv.get('payment_status') == 'paid':
                monthly[key]['paid'] += total
            else:
                monthly[key]['unpaid'] += total
        except Exception:
            pass
    result = []
    for i in range(5, -1, -1):
        d = datetime.now().replace(day=1) - timedelta(days=i * 28)
        key = d.strftime('%b %Y')
        lbl = d.strftime('%b')
        result.append({
            'label': lbl,
            'paid': round(monthly[key]['paid'], 2),
            'unpaid': round(monthly[key]['unpaid'], 2),
            'total': round(monthly[key]['total'], 2)
        })
    return result

def get_top_customers(invoices, customers, limit=5):
    totals = defaultdict(float)
    for inv in invoices:
        cid = inv.get('customer_id', '')
        if cid:
            totals[cid] += inv.get('total', 0)
    cust_map = {c['id']: c for c in customers}
    sorted_custs = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]
    result = []
    for cid, total in sorted_custs:
        c = cust_map.get(cid, {})
        result.append({
            'name': c.get('company') or c.get('name', 'Unknown'),
            'total': round(total, 2)
        })
    return result

# ---- AUTH ROUTES ----

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        user = find_user_by_email(email)
        if user and user.get('active') and user['password_hash'] == hash_password(password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            flash(f"Welcome back, {user['name']}!", 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = find_user_by_email(email)
        if user:
            otp = generate_otp()
            _otp_store[email.lower()] = {
                'otp': otp,
                'expires': datetime.now() + timedelta(minutes=10),
                'verified': False
            }
            sent = send_otp_email(user['email'], otp)
            if sent:
                flash('OTP sent to your email! Check your inbox.', 'success')
            else:
                flash(f'Email not sent. For testing, OTP is: {otp}', 'info')
            session['reset_email'] = email.lower()
            return redirect(url_for('verify_otp'))
        else:
            flash('No account found with that email address.', 'error')
    return render_template('forgot_password.html')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('reset_email')
    if not email:
        return redirect(url_for('forgot_password'))
    record = _otp_store.get(email)
    if not record or datetime.now() > record['expires']:
        flash('OTP expired. Please request a new one.', 'error')
        session.pop('reset_email', None)
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        entered = request.form.get('otp', '').strip()
        if entered == record['otp']:
            _otp_store[email]['verified'] = True
            return redirect(url_for('reset_password'))
        else:
            flash('Invalid OTP. Please try again.', 'error')
    return render_template('verify_otp.html', email=email)

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    email = session.get('reset_email')
    if not email:
        return redirect(url_for('forgot_password'))
    record = _otp_store.get(email)
    if not record or not record.get('verified') or datetime.now() > record['expires']:
        flash('Session expired. Please start again.', 'error')
        session.pop('reset_email', None)
        return redirect(url_for('forgot_password'))
    if request.method == 'POST':
        pwd = request.form.get('password', '')
        pwd2 = request.form.get('confirm_password', '')
        if len(pwd) < 6:
            flash('Password must be at least 6 characters.', 'error')
        elif pwd != pwd2:
            flash('Passwords do not match.', 'error')
        else:
            users = load_users()
            for u in users:
                if u['email'].lower() == email:
                    u['password_hash'] = hash_password(pwd)
            save_users(users)
            _otp_store.pop(email, None)
            session.pop('reset_email', None)
            flash('Password reset successfully! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('reset_password.html')

# ---- USER MANAGEMENT (Admin only) ----

@app.route('/admin/users')
@admin_required
def admin_users():
    users = load_users()
    return render_template('admin_users.html', users=users)

@app.route('/admin/users/add', methods=['POST'])
@admin_required
def admin_add_user():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'user')
    if not name or not email or not password:
        flash('All fields are required.', 'error')
        return redirect(url_for('admin_users'))
    if find_user_by_email(email):
        flash('A user with that email already exists.', 'error')
        return redirect(url_for('admin_users'))
    users = load_users()
    users.append({
        'id': f"user_{uuid.uuid4().hex[:8]}",
        'email': email,
        'password_hash': hash_password(password),
        'role': role,
        'name': name,
        'active': True
    })
    save_users(users)
    flash(f'User {name} created successfully!', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/delete/<uid>', methods=['POST'])
@admin_required
def admin_delete_user(uid):
    if uid == 'admin_001':
        flash('Cannot delete the default admin.', 'error')
        return redirect(url_for('admin_users'))
    users = [u for u in load_users() if u['id'] != uid]
    save_users(users)
    flash('User deleted.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/toggle/<uid>', methods=['POST'])
@admin_required
def admin_toggle_user(uid):
    if uid == 'admin_001':
        flash('Cannot deactivate the default admin.', 'error')
        return redirect(url_for('admin_users'))
    users = load_users()
    for u in users:
        if u['id'] == uid:
            u['active'] = not u.get('active', True)
    save_users(users)
    flash('User status updated.', 'success')
    return redirect(url_for('admin_users'))

# ---- DASHBOARD ----

@app.route('/')
@login_required
def dashboard():
    customers = load_json('customers.json')
    quotations = load_json('quotations.json')
    proformas = load_json('proformas.json')
    invoices = load_json('invoices.json')
    settings = load_settings()
    total_sales = sum(float(d.get('total', 0) or 0) for d in invoices)

    paid_total = 0.0
    unpaid_total = 0.0
    for inv in invoices:
        total = float(inv.get('total', 0) or 0)
        status = (inv.get('payment_status', 'unpaid') or 'unpaid').lower()

        amt_paid = inv.get('amount_paid', None)
        if amt_paid is None:
            amt_paid = total if status == 'paid' else 0.0
        try:
            amt_paid = float(amt_paid or 0)
        except Exception:
            amt_paid = 0.0

        bal_due = inv.get('balance_due', None)
        if bal_due is None:
            bal_due = max(total - amt_paid, 0.0)
        try:
            bal_due = float(bal_due or 0)
        except Exception:
            bal_due = max(total - amt_paid, 0.0)

        paid_total += max(min(amt_paid, total), 0.0)
        unpaid_total += max(min(bal_due, total), 0.0)

    paid_percent = (paid_total / total_sales * 100.0) if total_sales > 0 else 0.0
    pending_percent = (unpaid_total / total_sales * 100.0) if total_sales > 0 else 0.0
    monthly = get_monthly_data(invoices)
    top_customers = get_top_customers(invoices, customers)
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template(
        'dashboard.html',
        customers=customers, quotations=quotations, proformas=proformas, invoices=invoices,
        total_sales=total_sales, paid_total=paid_total, unpaid_total=unpaid_total,
        paid_percent=round(paid_percent, 2), pending_percent=round(pending_percent, 2),
        monthly=monthly, settings=settings, today=today, top_customers=top_customers
    )

# ---- CUSTOMERS ----

@app.route('/customers')
@login_required
def customers():
    data = load_json('customers.json')
    all_invoices = load_json('invoices.json')
    rev_map = defaultdict(float)
    for inv in all_invoices:
        rev_map[inv.get('customer_id', '')] += inv.get('total', 0)
    return render_template('customers.html', customers=data, rev_map=rev_map)

@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        data = load_json('customers.json')
        customer = {
            'id': str(uuid.uuid4()),
            'type': request.form.get('type', 'individual'),
            'name': request.form.get('name', ''),
            'company': request.form.get('company', ''),
            'email': request.form.get('email', ''),
            'phone': request.form.get('phone', ''),
            'address': request.form.get('address', ''),
            'city': request.form.get('city', ''),
            'state': request.form.get('state', 'Gujarat'),
            'state_code': request.form.get('state_code', '24'),
            'gstin': request.form.get('gstin', '').upper(),
            'pan': request.form.get('pan', ''),
            'created_at': datetime.now().strftime('%Y-%m-%d')
        }
        data.append(customer)
        save_json('customers.json', data)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'customer': customer})
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=None)

@app.route('/api/customers/add', methods=['POST'])
@login_required
def api_add_customer():
    data = load_json('customers.json')
    payload = request.get_json(silent=True) or {}
    customer = {
        'id': str(uuid.uuid4()),
        'type': payload.get('type', 'individual'),
        'name': payload.get('name', ''),
        'company': payload.get('company', ''),
        'email': payload.get('email', ''),
        'phone': payload.get('phone', ''),
        'address': payload.get('address', ''),
        'city': payload.get('city', ''),
        'state': payload.get('state', 'Gujarat'),
        'state_code': payload.get('state_code', '24'),
        'gstin': payload.get('gstin', '').upper(),
        'pan': payload.get('pan', ''),
        'created_at': datetime.now().strftime('%Y-%m-%d')
    }
    data.append(customer)
    save_json('customers.json', data)
    return jsonify({'success': True, 'customer': customer})

@app.route('/customers/edit/<cid>', methods=['GET', 'POST'])
@login_required
def edit_customer(cid):
    data = load_json('customers.json')
    customer = next((c for c in data if c['id'] == cid), None)
    if request.method == 'POST':
        for c in data:
            if c['id'] == cid:
                c['type'] = request.form.get('type', 'individual')
                c['name'] = request.form.get('name', '')
                c['company'] = request.form.get('company', '')
                c['email'] = request.form.get('email', '')
                c['phone'] = request.form.get('phone', '')
                c['address'] = request.form.get('address', '')
                c['city'] = request.form.get('city', '')
                c['state'] = request.form.get('state', '')
                c['state_code'] = request.form.get('state_code', '')
                c['gstin'] = request.form.get('gstin', '').upper()
                c['pan'] = request.form.get('pan', '')
        save_json('customers.json', data)
        return redirect(url_for('customers'))
    return render_template('customer_form.html', customer=customer)

@app.route('/customers/delete/<cid>', methods=['POST'])
@login_required
def delete_customer(cid):
    data = load_json('customers.json')
    data = [c for c in data if c['id'] != cid]
    save_json('customers.json', data)
    return redirect(url_for('customers'))

@app.route('/customers/history/<cid>')
@login_required
def customer_history(cid):
    customers_data = load_json('customers.json')
    customer = next((c for c in customers_data if c['id'] == cid), None)
    if not customer:
        return redirect(url_for('customers'))
    quotations = [q for q in load_json('quotations.json') if q.get('customer_id') == cid]
    proformas = [p for p in load_json('proformas.json') if p.get('customer_id') == cid]
    invoices = [i for i in load_json('invoices.json') if i.get('customer_id') == cid]
    total_billed = sum(i.get('total', 0) for i in invoices)
    total_paid = sum(i.get('total', 0) for i in invoices if i.get('payment_status') == 'paid')
    return render_template(
        'customer_history.html',
        customer=customer,
        quotations=quotations,
        proformas=proformas,
        invoices=invoices,
        total_billed=total_billed,
        total_paid=total_paid
    )

@app.route('/api/customers')
@login_required
def api_customers():
    return jsonify(load_json('customers.json'))

# ---- ITEMS ----

def _items_path():
    return os.path.join(DATA_DIR, 'items.json')

@app.route('/items')
@login_required
def items():
    data = load_json('items.json') if os.path.exists(_items_path()) else []
    return render_template('items.html', items=data)

@app.route('/items/add', methods=['POST'])
@login_required
def add_item():
    data = load_json('items.json') if os.path.exists(_items_path()) else []
    item = {
        'id': str(uuid.uuid4()),
        'name': request.form.get('name', ''),
        'description': request.form.get('description', ''),
        'unit': request.form.get('unit', 'nos'),
        'rate': float(request.form.get('rate', 0)),
        'hsn_sac': request.form.get('hsn_sac', ''),
        'tax': float(request.form.get('tax', 18))
    }
    data.append(item)
    save_json('items.json', data)
    return redirect(url_for('items'))

@app.route('/items/delete/<iid>', methods=['POST'])
@login_required
def delete_item(iid):
    data = load_json('items.json') if os.path.exists(_items_path()) else []
    data = [i for i in data if i['id'] != iid]
    save_json('items.json', data)
    return redirect(url_for('items'))

@app.route('/api/items')
@login_required
def api_items():
    data = load_json('items.json') if os.path.exists(_items_path()) else []
    return jsonify(data)

# ---- GST LOOKUP ----

@app.route('/api/gst-lookup', methods=['POST'])
@login_required
def gst_lookup():
    payload = request.get_json(silent=True) or {}
    gstin = payload.get('gstin', '').strip().upper()
    if not gstin:
        return jsonify({'error': 'GSTIN is required'}), 400

    # Validate format: 2 digits state + 5 alpha + 4 digits + 1 alpha + 1 alphanumeric + Z + 1 alphanumeric
    if not re.match(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$', gstin):
        return jsonify({'error': 'Invalid GSTIN format. Example: 24XXXXX1234X1ZX'}), 400

    state_code = gstin[:2]
    state_name = GST_STATE_CODES.get(state_code, 'Unknown')

    settings_data = load_settings()
    gst_api_key = (settings_data.get('gst_api_key', '') or os.environ.get('GST_API_KEY', '')).strip()

    if gst_api_key and HAS_REQUESTS:
        try:
            resp = req_lib.get(
                f"https://sheet.gstincheck.co.in/check/{gst_api_key}/{gstin}",
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('flag'):
                    gst_data = data.get('data', {})
                    pradr = gst_data.get('pradr', {})
                    addr_obj = pradr.get('addr', {})
                    addr_parts = [p for p in [
                        addr_obj.get('bnm', ''), addr_obj.get('bno', ''),
                        addr_obj.get('st', ''), addr_obj.get('loc', ''),
                        addr_obj.get('dst', ''), addr_obj.get('stcd', ''),
                        str(addr_obj.get('pncd', ''))
                    ] if p]
                    addr_str = ', '.join(addr_parts) or pradr.get('adr', '')
                    return jsonify({
                        'success': True,
                        'gstin': gstin,
                        'company_name': gst_data.get('lgnm', ''),
                        'trade_name': gst_data.get('tradeNam', ''),
                        'address': addr_str,
                        'state': state_name,
                        'state_code': state_code,
                        'status': gst_data.get('sts', ''),
                    })
                else:
                    return jsonify({'error': data.get('message', 'GSTIN not found or inactive')}), 404
            else:
                return jsonify({'error': f'GST API request failed with status {resp.status_code}'}), 502
        except Exception as e:
            return jsonify({'error': f'GST API request failed: {str(e)}'}), 502

    # Fallback: state from GSTIN digits
    return jsonify({
        'success': True,
        'partial': True,
        'gstin': gstin,
        'state': state_name,
        'state_code': state_code,
        'message': f'State auto-detected as {state_name} ({state_code}). Add a GST API key in Settings for full lookup.'
    })

# ---- QUOTATIONS ----

@app.route('/quotations')
@login_required
def quotations():
    data = load_json('quotations.json')
    custs = {c['id']: c for c in load_json('customers.json')}
    return render_template('quotations.html', quotations=data, customers=custs)

@app.route('/quotations/new', methods=['GET', 'POST'])
@login_required
def new_quotation():
    if request.method == 'POST':
        return save_document('quotation')
    custs = load_json('customers.json')
    items_list = load_json('items.json') if os.path.exists(_items_path()) else []
    settings = load_settings()
    today = datetime.now().strftime('%Y-%m-%d')
    next_num = peek_next_number('quotation')
    return render_template('document_form.html', doc_type='quotation', customers=custs,
                           items=items_list, doc=None, settings=settings, today=today, next_num=next_num)

@app.route('/quotations/edit/<did>', methods=['GET', 'POST'])
@login_required
def edit_quotation(did):
    if request.method == 'POST':
        return save_document('quotation', did)
    data = load_json('quotations.json')
    doc = next((d for d in data if d['id'] == did), None)
    custs = load_json('customers.json')
    items_list = load_json('items.json') if os.path.exists(_items_path()) else []
    settings = load_settings()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('document_form.html', doc_type='quotation', customers=custs,
                           items=items_list, doc=doc, settings=settings, today=today,
                           next_num=doc['number'] if doc else '')

@app.route('/quotations/delete/<did>', methods=['POST'])
@login_required
def delete_quotation(did):
    data = load_json('quotations.json')
    data = [d for d in data if d['id'] != did]
    save_json('quotations.json', data)
    return redirect(url_for('quotations'))

@app.route('/quotations/convert/<did>', methods=['POST'])
@login_required
def convert_quotation(did):
    target = request.form.get('target', 'proforma')
    quotations_data = load_json('quotations.json')
    doc = next((d for d in quotations_data if d['id'] == did), None)
    if not doc:
        return redirect(url_for('quotations'))
    # Block if already converted or invoiced
    if doc.get('status') in ('converted', 'invoiced'):
        flash(f'Quotation {doc.get("number","")} has already been converted and cannot be converted again.', 'error')
        return redirect(url_for('quotations'))
    if target == 'proforma':
        proformas_data = load_json('proformas.json')
        new_doc = dict(doc)
        new_doc['id'] = str(uuid.uuid4())
        new_doc['number'] = get_next_number('proforma')
        new_doc['doc_type'] = 'proforma'
        new_doc['date'] = datetime.now().strftime('%Y-%m-%d')
        new_doc['source_quotation'] = doc['number']
        new_doc['status'] = 'draft'
        proformas_data.append(new_doc)
        save_json('proformas.json', proformas_data)
        for q in quotations_data:
            if q['id'] == did:
                q['status'] = 'converted'
        save_json('quotations.json', quotations_data)
        return redirect(url_for('proformas'))
    elif target == 'invoice':
        invoices_data = load_json('invoices.json')
        new_doc = dict(doc)
        issue_date = datetime.now().strftime('%Y-%m-%d')
        new_doc['id'] = str(uuid.uuid4())
        new_doc['number'] = get_next_number('invoice')
        new_doc['doc_type'] = 'invoice'
        new_doc['date'] = issue_date
        new_doc['payment_terms'] = 'net_15'
        new_doc['due_date'] = calculate_due_date(issue_date, 'net_15')
        new_doc['source_quotation'] = doc['number']
        new_doc['payment_status'] = 'unpaid'
        new_doc['status'] = 'draft'
        invoices_data.append(new_doc)
        save_json('invoices.json', invoices_data)
        for q in quotations_data:
            if q['id'] == did:
                q['status'] = 'invoiced'
        save_json('quotations.json', quotations_data)
        return redirect(url_for('invoices'))
    return redirect(url_for('quotations'))

# ---- PROFORMAS ----

@app.route('/proformas')
@login_required
def proformas():
    data = load_json('proformas.json')
    custs = {c['id']: c for c in load_json('customers.json')}
    return render_template('proformas.html', proformas=data, customers=custs)

@app.route('/proformas/new', methods=['GET', 'POST'])
@login_required
def new_proforma():
    if request.method == 'POST':
        return save_document('proforma')
    custs = load_json('customers.json')
    items_list = load_json('items.json') if os.path.exists(_items_path()) else []
    settings = load_settings()
    today = datetime.now().strftime('%Y-%m-%d')
    next_num = peek_next_number('proforma')
    return render_template('document_form.html', doc_type='proforma', customers=custs,
                           items=items_list, doc=None, settings=settings, today=today, next_num=next_num)

@app.route('/proformas/edit/<did>', methods=['GET', 'POST'])
@login_required
def edit_proforma(did):
    if request.method == 'POST':
        return save_document('proforma', did)
    data = load_json('proformas.json')
    doc = next((d for d in data if d['id'] == did), None)
    custs = load_json('customers.json')
    items_list = load_json('items.json') if os.path.exists(_items_path()) else []
    settings = load_settings()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('document_form.html', doc_type='proforma', customers=custs,
                           items=items_list, doc=doc, settings=settings, today=today,
                           next_num=doc['number'] if doc else '')

@app.route('/proformas/delete/<did>', methods=['POST'])
@login_required
def delete_proforma(did):
    data = load_json('proformas.json')
    data = [d for d in data if d['id'] != did]
    save_json('proformas.json', data)
    return redirect(url_for('proformas'))

@app.route('/proformas/convert/<did>', methods=['POST'])
@login_required
def convert_proforma(did):
    proformas_data = load_json('proformas.json')
    doc = next((d for d in proformas_data if d['id'] == did), None)
    if not doc:
        return redirect(url_for('proformas'))
    # Block if already invoiced
    if doc.get('status') == 'invoiced':
        flash(f'Proforma {doc.get("number","")} has already been converted to an invoice and cannot be converted again.', 'error')
        return redirect(url_for('proformas'))
    if doc:
        invoices_data = load_json('invoices.json')
        new_doc = dict(doc)
        issue_date = datetime.now().strftime('%Y-%m-%d')
        new_doc['id'] = str(uuid.uuid4())
        new_doc['number'] = get_next_number('invoice')
        new_doc['doc_type'] = 'invoice'
        new_doc['date'] = issue_date
        new_doc['payment_terms'] = 'net_15'
        new_doc['due_date'] = calculate_due_date(issue_date, 'net_15')
        new_doc['source_proforma'] = doc['number']
        new_doc['payment_status'] = 'unpaid'
        new_doc['status'] = 'draft'
        invoices_data.append(new_doc)
        save_json('invoices.json', invoices_data)
        for p in proformas_data:
            if p['id'] == did:
                p['status'] = 'invoiced'
        save_json('proformas.json', proformas_data)
    return redirect(url_for('invoices'))

# ---- INVOICES ----

@app.route('/invoices')
@login_required
def invoices():
    data = load_json('invoices.json')
    custs = {c['id']: c for c in load_json('customers.json')}

    grand_total = 0.0
    received_total = 0.0
    pending_total = 0.0
    for inv in data:
        total = float(inv.get('total', 0) or 0)
        status = (inv.get('payment_status', 'unpaid') or 'unpaid').lower()
        amt_paid = inv.get('amount_paid', None)
        bal_due = inv.get('balance_due', None)

        if amt_paid is None:
            if status == 'paid':
                amt_paid = total
            else:
                amt_paid = 0.0
        try:
            amt_paid = float(amt_paid or 0)
        except Exception:
            amt_paid = 0.0

        if bal_due is None:
            bal_due = max(total - amt_paid, 0.0)
        try:
            bal_due = float(bal_due or 0)
        except Exception:
            bal_due = max(total - amt_paid, 0.0)

        amt_paid = max(min(amt_paid, total), 0.0)
        bal_due = max(min(bal_due, total), 0.0)

        grand_total += total
        received_total += amt_paid
        pending_total += bal_due

    paid_percent = (received_total / grand_total * 100.0) if grand_total > 0 else 0.0
    pending_percent = (pending_total / grand_total * 100.0) if grand_total > 0 else 0.0

    return render_template(
        'invoices.html',
        invoices=data,
        customers=custs,
        received_total=round(received_total, 2),
        pending_total=round(pending_total, 2),
        paid_percent=round(paid_percent, 2),
        pending_percent=round(pending_percent, 2),
    )

@app.route('/invoices/new', methods=['GET', 'POST'])
@login_required
def new_invoice():
    if request.method == 'POST':
        return save_document('invoice')
    custs = load_json('customers.json')
    items_list = load_json('items.json') if os.path.exists(_items_path()) else []
    settings = load_settings()
    today = datetime.now().strftime('%Y-%m-%d')
    next_num = peek_next_number('invoice')
    return render_template('document_form.html', doc_type='invoice', customers=custs,
                           items=items_list, doc=None, settings=settings, today=today, next_num=next_num)

@app.route('/invoices/edit/<did>', methods=['GET', 'POST'])
@login_required
def edit_invoice(did):
    if request.method == 'POST':
        return save_document('invoice', did)
    data = load_json('invoices.json')
    doc = next((d for d in data if d['id'] == did), None)
    custs = load_json('customers.json')
    items_list = load_json('items.json') if os.path.exists(_items_path()) else []
    settings = load_settings()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('document_form.html', doc_type='invoice', customers=custs,
                           items=items_list, doc=doc, settings=settings, today=today,
                           next_num=doc['number'] if doc else '')

@app.route('/invoices/delete/<did>', methods=['POST'])
@login_required
def delete_invoice(did):
    data = load_json('invoices.json')
    data = [d for d in data if d['id'] != did]
    save_json('invoices.json', data)
    return redirect(url_for('invoices'))

@app.route('/invoices/mark-paid/<did>', methods=['POST'])
@login_required
def mark_paid(did):
    data = load_json('invoices.json')
    for d in data:
        if d['id'] == did:
            d['payment_status'] = 'paid'
            d['status'] = 'paid'
            d['amount_paid'] = round(float(d.get('total', 0)), 2)
            d['balance_due'] = 0.0
            d['paid_date'] = datetime.now().strftime('%Y-%m-%d')
    save_json('invoices.json', data)
    return redirect(url_for('invoices'))

# ---- CASHFREE PAYMENT INTEGRATION ----

@app.route('/invoices/payment-link/<did>', methods=['POST'])
@login_required
def generate_payment_link(did):
    if not HAS_REQUESTS:
        return jsonify({'error': 'requests library is not installed'}), 500

    invoices_data = load_json('invoices.json')
    doc = next((d for d in invoices_data if d['id'] == did), None)
    if not doc:
        return jsonify({'error': 'Invoice not found'}), 404

    settings_data = load_settings()
    cf_app_id = settings_data.get('cashfree_app_id', '').strip()
    cf_secret = settings_data.get('cashfree_secret', '').strip()
    cf_env = settings_data.get('cashfree_env', 'sandbox')

    if not cf_app_id or not cf_secret:
        return jsonify({
            'error': 'Cashfree credentials not configured. Go to Settings → Payment Gateway and add your App ID and Secret Key.'
        }), 400

    base_url = 'https://api.cashfree.com' if cf_env == 'production' else 'https://sandbox.cashfree.com'

    custs = load_json('customers.json')
    customer = next((c for c in custs if c['id'] == doc.get('customer_id')), {})

    # Sanitize phone (Cashfree requires 10-digit mobile number)
    raw_phone = customer.get('phone', '9999999999')
    phone = re.sub(r'[^0-9]', '', raw_phone)[-10:] or '9999999999'
    if len(phone) < 10:
        phone = '9999999999'

    # Unique link_id (max 50 chars)
    link_id = re.sub(r'[^a-zA-Z0-9_]', '_', f"inv_{did}")[:50]

    payload = {
        "link_id": link_id,
        "link_amount": float(doc.get('balance_due', doc.get('total', 0)) or 0),
        "link_currency": "INR",
        "link_purpose": f"Invoice {doc.get('number', '')}",
        "customer_details": {
            "customer_phone": phone,
            "customer_name": (customer.get('company') or customer.get('name', 'Customer'))[:50],
            "customer_email": customer.get('email', 'billing@example.com'),
        },
        "link_notify": {"send_sms": False, "send_email": False},
        "link_meta": {
            "return_url": request.host_url.rstrip('/') + f"/invoices/payment-return/{did}"
        }
    }

    headers = {
        'x-client-id': cf_app_id,
        'x-client-secret': cf_secret,
        'x-api-version': '2022-09-01',
        'Content-Type': 'application/json'
    }

    try:
        resp = req_lib.post(f"{base_url}/pl/links", json=payload, headers=headers, timeout=15)
        result = resp.json()
        if resp.status_code in (200, 201) and result.get('link_url'):
            link_url = result['link_url']
            for inv in invoices_data:
                if inv['id'] == did:
                    inv['payment_link'] = link_url
                    inv['payment_link_id'] = link_id
                    inv['status'] = 'sent'
            save_json('invoices.json', invoices_data)
            return jsonify({'success': True, 'payment_link': link_url})
        else:
            msg = result.get('message', result.get('error', 'Payment link creation failed'))
            return jsonify({'error': msg, 'cf_response': result}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/invoices/payment-return/<did>')
@login_required
def payment_return(did):
    """Customer returns here after paying via Cashfree."""
    invoices_data = load_json('invoices.json')
    doc = next((d for d in invoices_data if d['id'] == did), None)
    if doc and doc.get('payment_link_id') and HAS_REQUESTS:
        settings_data = load_settings()
        cf_app_id = settings_data.get('cashfree_app_id', '')
        cf_secret = settings_data.get('cashfree_secret', '')
        cf_env = settings_data.get('cashfree_env', 'sandbox')
        if cf_app_id and cf_secret:
            base_url = 'https://api.cashfree.com' if cf_env == 'production' else 'https://sandbox.cashfree.com'
            headers = {
                'x-client-id': cf_app_id,
                'x-client-secret': cf_secret,
                'x-api-version': '2022-09-01'
            }
            try:
                link_id = doc['payment_link_id']
                resp = req_lib.get(f"{base_url}/pl/links/{link_id}/orders",
                                   headers=headers, timeout=10)
                if resp.status_code == 200:
                    orders = resp.json()
                    for order in orders.get('link_orders', []):
                        if order.get('order_status') == 'PAID':
                            for inv in invoices_data:
                                if inv['id'] == did:
                                    inv['payment_status'] = 'paid'
                                    inv['status'] = 'paid'
                                    inv['amount_paid'] = round(float(inv.get('total', 0)), 2)
                                    inv['balance_due'] = 0.0
                                    inv['paid_date'] = datetime.now().strftime('%Y-%m-%d')
                            save_json('invoices.json', invoices_data)
                            break
            except Exception:
                pass
    return redirect(url_for('invoices'))

@app.route('/cashfree/webhook', methods=['POST'])
@login_required
def cashfree_webhook():
    """Cashfree payment webhook — auto-updates invoice status to Paid."""
    raw_payload = request.get_data(as_text=True)
    received_sig = request.headers.get('x-webhook-signature', '')

    settings_data = load_settings()
    cf_secret = settings_data.get('cashfree_secret', '')

    # Verify signature (Cashfree uses HMAC-SHA256)
    if cf_secret and received_sig:
        import hmac as _hmac
        expected = _hmac.new(
            cf_secret.encode('utf-8'), raw_payload.encode('utf-8'), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, received_sig):
            return jsonify({'error': 'Invalid signature'}), 403

    data = request.get_json(silent=True) or {}
    event_type = data.get('type', '')

    if event_type in ('PAYMENT_SUCCESS_WEBHOOK', 'PAYMENT_SUCCESS', 'PAYMENT_LINK_SUCCESS'):
        order_data = data.get('data', {})
        link_info = order_data.get('link', {})
        payment_info = order_data.get('payment', {})

        link_id = link_info.get('link_id', '') or order_data.get('order', {}).get('order_id', '')
        if link_id:
            invoices_data = load_json('invoices.json')
            updated = False
            for inv in invoices_data:
                if inv.get('payment_link_id') == link_id:
                    inv['payment_status'] = 'paid'
                    inv['status'] = 'paid'
                    inv['amount_paid'] = round(float(inv.get('total', 0)), 2)
                    inv['balance_due'] = 0.0
                    inv['paid_date'] = datetime.now().strftime('%Y-%m-%d')
                    inv['cf_payment_id'] = payment_info.get('cf_payment_id', '')
                    updated = True
            if updated:
                save_json('invoices.json', invoices_data)

    return jsonify({'status': 'ok'})

# ---- PDF ----

@app.route('/pdf/<doc_type>/<did>')
@login_required
def download_pdf(doc_type, did):
    file_map = {'quotation': 'quotations.json', 'proforma': 'proformas.json', 'invoice': 'invoices.json'}
    data = load_json(file_map.get(doc_type, 'quotations.json'))
    doc = next((d for d in data if d['id'] == did), None)
    if not doc:
        return "Document not found", 404
    custs = load_json('customers.json')
    customer = next((c for c in custs if c['id'] == doc.get('customer_id')), {})
    settings = load_settings()
    pdf_path = generate_pdf(doc, customer, settings, doc_type)
    resp = send_file(pdf_path, as_attachment=True, download_name=f"{doc.get('number', 'doc')}.pdf")
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/preview/<doc_type>/<did>')
@login_required
def preview_pdf(doc_type, did):
    file_map = {'quotation': 'quotations.json', 'proforma': 'proformas.json', 'invoice': 'invoices.json'}
    data = load_json(file_map.get(doc_type, 'quotations.json'))
    doc = next((d for d in data if d['id'] == did), None)
    if not doc:
        return "Document not found", 404
    custs = load_json('customers.json')
    customer = next((c for c in custs if c['id'] == doc.get('customer_id')), {})
    settings = load_settings()
    pdf_path = generate_pdf(doc, customer, settings, doc_type)
    resp = send_file(pdf_path, as_attachment=False,
                     download_name=f"{doc.get('number', 'doc')}.pdf",
                     mimetype='application/pdf')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

# ---- SETTINGS ----

@app.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    if request.method == 'POST':
        s = {}
        # Editable fields only
        for key in ['bank_name', 'account_number', 'account_name', 'branch', 'ifsc', 'upi',
                    'terms', 'cashfree_app_id', 'cashfree_secret', 'cashfree_env', 'gst_api_key']:
            val = request.form.get(key)
            if val is not None:
                s[key] = val

        # Signature upload
        if 'signature' in request.files:
            sig_file = request.files['signature']
            if sig_file and sig_file.filename:
                ext = sig_file.filename.rsplit('.', 1)[-1].lower()
                if ext in ('png', 'jpg', 'jpeg'):
                    filename = f"sign_{uuid.uuid4().hex[:8]}.{ext}"
                    os.makedirs(UPLOAD_DIR, exist_ok=True)
                    sig_file.save(os.path.join(UPLOAD_DIR, filename))
                    s['signature'] = filename

        # Logo upload
        if 'logo' in request.files:
            logo_file = request.files['logo']
            if logo_file and logo_file.filename:
                ext = logo_file.filename.rsplit('.', 1)[-1].lower()
                if ext in ('png', 'jpg', 'jpeg'):
                    os.makedirs(LOGO_UPLOAD_DIR, exist_ok=True)
                    filename = f"logo_{uuid.uuid4().hex[:8]}.{ext}"
                    logo_file.save(os.path.join(LOGO_UPLOAD_DIR, filename))
                    s['logo'] = filename

        save_settings(s)
        flash('Settings saved successfully!', 'success')
        return redirect(url_for('settings'))

    s = load_settings()
    return render_template('settings.html', settings=s, fixed=FIXED_COMPANY)

# ---- SAVE DOCUMENT HELPER ----

def save_document(doc_type, existing_id=None):
    file_map = {'quotation': 'quotations.json', 'proforma': 'proformas.json', 'invoice': 'invoices.json'}
    data = load_json(file_map[doc_type])

    item_names = request.form.getlist('item_name[]')
    item_descs = request.form.getlist('item_desc[]')
    item_hsns = request.form.getlist('item_hsn[]')
    item_qtys = request.form.getlist('item_qty[]')
    item_rates = request.form.getlist('item_rate[]')
    item_taxes = request.form.getlist('item_tax[]')
    item_discounts = request.form.getlist('item_discount[]')
    item_units = request.form.getlist('item_unit[]')

    # Determine whether to use IGST (inter-state) or CGST+SGST (intra-state)
    cust_id_form = request.form.get('customer_id', '')
    new_cust_sc = request.form.get('new_customer_state_code', '24').strip()
    if cust_id_form and not request.form.get('new_customer_name', '').strip():
        custs_list = load_json('customers.json')
        existing_c = next((c for c in custs_list if c['id'] == cust_id_form), {})
        cust_sc = existing_c.get('state_code', '24') or '24'
    else:
        cust_sc = new_cust_sc or '24'

    use_igst = (cust_sc != FIXED_COMPANY['state_code']) and bool(cust_sc)
    gst_enabled = request.form.get('gst_enabled', 'off') == 'on'

    line_items = []
    subtotal = 0.0
    total_tax = 0.0

    for i in range(len(item_names)):
        if not item_names[i].strip():
            continue
        qty = float(item_qtys[i] or 1) if i < len(item_qtys) else 1.0
        rate = float(item_rates[i] or 0) if i < len(item_rates) else 0.0
        # Force tax to 0 for non-GST documents
        if gst_enabled:
            tax_pct = float(item_taxes[i] or 0) if i < len(item_taxes) else 18.0
        else:
            tax_pct = 0.0
        discount = float(item_discounts[i] or 0) if i < len(item_discounts) else 0.0

        base_amount = qty * rate
        discount_amt = base_amount * discount / 100
        taxable = base_amount - discount_amt

        if gst_enabled:
            if use_igst:
                cgst, sgst = 0.0, 0.0
                igst = round(taxable * tax_pct / 100, 2)
                item_tax_total = igst
            else:
                cgst = round(taxable * tax_pct / 2 / 100, 2)
                sgst = round(taxable * tax_pct / 2 / 100, 2)
                igst = 0.0
                item_tax_total = cgst + sgst
            line_total = taxable + item_tax_total
            subtotal += taxable
            total_tax += item_tax_total
            line_items.append({
                'name': item_names[i].strip(),
                'description': (item_descs[i] if i < len(item_descs) else '').strip(),
                'hsn_sac': (item_hsns[i] if i < len(item_hsns) else '').strip(),
                'unit': item_units[i] if i < len(item_units) else 'nos',
                'qty': qty, 'rate': rate, 'discount': discount, 'tax': tax_pct,
                'cgst': cgst, 'sgst': sgst, 'igst': igst,
                'amount': round(line_total, 2)
            })
        else:
            # Non-GST: ignore GST fields and tax
            cgst = sgst = igst = item_tax_total = 0.0
            line_total = taxable
            subtotal += taxable
            # total_tax remains 0
            line_items.append({
                'name': item_names[i].strip(),
                'description': (item_descs[i] if i < len(item_descs) else '').strip(),
                'hsn_sac': (item_hsns[i] if i < len(item_hsns) else '').strip(),
                'unit': item_units[i] if i < len(item_units) else 'nos',
                'qty': qty, 'rate': rate, 'discount': discount, 'tax': 0.0,
                'cgst': 0.0, 'sgst': 0.0, 'igst': 0.0,
                'amount': round(line_total, 2)
            })

    if not line_items:
        flash('Please add at least one line item with item name.', 'error')
        return redirect(request.url)

    # Always recalculate total and total_tax based on current GST setting and line items
    total = round(subtotal + total_tax, 2)
    # If GST is disabled, force total_tax to 0 and total to subtotal (for all doc types)
    if not gst_enabled:
        total_tax = 0.0
        total = round(subtotal, 2)


    # Handle inline new customer creation
    cust_id = cust_id_form
    new_customer_name = request.form.get('new_customer_name', '').strip()
    new_customer_type = request.form.get('new_customer_type', 'individual').strip().lower()
    new_customer_gstin = request.form.get('new_customer_gstin', '').upper().strip()

    if not cust_id and not new_customer_name:
        flash('Please select an existing client or enter new client name.', 'error')
        return redirect(request.url)

    if new_customer_type == 'business' and not cust_id and not new_customer_gstin:
        flash('GSTIN is required for business clients.', 'error')
        return redirect(request.url)

    if new_customer_gstin and not re.match(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$', new_customer_gstin):
        flash('Invalid GSTIN format. Example: 24XXXXX1234X1ZX', 'error')
        return redirect(request.url)

    if cust_id and not new_customer_name:
        custs_list = load_json('customers.json')
        existing_c = next((c for c in custs_list if c['id'] == cust_id), None)
        if not existing_c:
            flash('Selected client does not exist.', 'error')
            return redirect(request.url)
        if (existing_c.get('type', 'individual') == 'business') and not (existing_c.get('gstin') or '').strip():
            flash('GSTIN is required for business clients. Please update customer GSTIN.', 'error')
            return redirect(request.url)

    if request.form.get('new_customer_name', '').strip():
        if not request.form.get('new_customer_state', '').strip():
            flash('Customer state is required.', 'error')
            return redirect(request.url)
        if not request.form.get('new_customer_state_code', '').strip():
            flash('Customer state code is required.', 'error')
            return redirect(request.url)
        if not request.form.get('new_customer_address', '').strip():
            flash('Customer address is required.', 'error')
            return redirect(request.url)
        if not request.form.get('new_customer_phone', '').strip():
            flash('Customer phone is required.', 'error')
            return redirect(request.url)

        custs = load_json('customers.json')
        new_c = {
            'id': str(uuid.uuid4()),
            'type': new_customer_type,
            'name': new_customer_name,
            'company': request.form.get('new_customer_company', '').strip(),
            'email': request.form.get('new_customer_email', '').strip(),
            'phone': request.form.get('new_customer_phone', '').strip(),
            'address': request.form.get('new_customer_address', '').strip(),
            'city': request.form.get('new_customer_city', '').strip(),
            'state': request.form.get('new_customer_state', 'Gujarat').strip(),
            'state_code': request.form.get('new_customer_state_code', '24').strip(),
            'gstin': new_customer_gstin,
            'pan': '',
            'created_at': datetime.now().strftime('%Y-%m-%d')
        }
        custs.append(new_c)
        save_json('customers.json', custs)
        cust_id = new_c['id']

    # Restrict only one document per customer per type
    if not existing_id and cust_id:
        # Only for new documents, not editing
        for d in data:
            if d.get('customer_id') == cust_id:
                flash(f'This customer already has a {doc_type}. Only one {doc_type} is allowed per customer. Please create a new customer for another {doc_type}.', 'error')
                return redirect(request.url)

    # Validate payment fields for invoice
    if doc_type == 'invoice':
        payment_status = request.form.get('payment_status', 'unpaid').strip().lower()
        online_paid_raw = request.form.get('online_paid', '0').strip()
        cash_paid_raw = request.form.get('cash_paid', '0').strip()
        try:
            online_paid = max(0.0, round(float(online_paid_raw or 0), 2))
        except Exception:
            online_paid = 0.0
        try:
            cash_paid = max(0.0, round(float(cash_paid_raw or 0), 2))
        except Exception:
            cash_paid = 0.0
        # Always update amount_paid from online_paid + cash_paid for partial
        if payment_status == 'partial':
            amount_paid = round(online_paid + cash_paid, 2)
            if amount_paid <= 0:
                flash('For partially paid invoice, enter online/cash received amount.', 'error')
                return redirect(request.url)
            if amount_paid >= total:
                payment_status = 'paid'
                amount_paid = total
                online_paid = 0.0
                cash_paid = 0.0
        elif payment_status == 'paid':
            amount_paid = total
            online_paid = 0.0
            cash_paid = 0.0
        else:
            amount_paid = 0.0
            online_paid = 0.0
            cash_paid = 0.0
    # ...existing code...

    # Resolve document number
    if existing_id:
        existing_doc = next((d for d in data if d['id'] == existing_id), {})
        doc_number = request.form.get('number') or existing_doc.get('number', get_next_number(doc_type))
    else:
        doc_number = request.form.get('number') or get_next_number(doc_type)

    issue_date = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
    if not issue_date:
        flash('Date is required.', 'error')
        return redirect(request.url)

    place_of_supply = request.form.get('place_of_supply', 'Gujarat (24)').strip()
    if not place_of_supply:
        flash('Place of Supply is required.', 'error')
        return redirect(request.url)

    payment_terms = request.form.get('payment_terms', 'due_on_receipt').strip()
    if payment_terms not in PAYMENT_TERMS_DAYS:
        payment_terms = 'due_on_receipt'

    due_date_input = request.form.get('due_date', '').strip()
    if doc_type == 'invoice':
        due_date = due_date_input or calculate_due_date(issue_date, payment_terms)
    else:
        due_date = due_date_input

    payment_status = request.form.get('payment_status', 'unpaid').strip().lower()
    if payment_status not in VALID_PAYMENT_STATUS:
        payment_status = 'unpaid'

    amount_paid_raw = request.form.get('amount_paid', '0').strip()
    try:
        amount_paid = float(amount_paid_raw or 0)
    except Exception:
        amount_paid = 0.0

    amount_paid = max(0.0, round(amount_paid, 2))
    online_paid_raw = request.form.get('online_paid', '0').strip()
    cash_paid_raw = request.form.get('cash_paid', '0').strip()
    try:
        online_paid = max(0.0, round(float(online_paid_raw or 0), 2))
    except Exception:
        online_paid = 0.0
    try:
        cash_paid = max(0.0, round(float(cash_paid_raw or 0), 2))
    except Exception:
        cash_paid = 0.0

    if doc_type == 'invoice':
        if payment_status == 'paid':
            amount_paid = total
            online_paid = 0.0
            cash_paid = 0.0
        elif payment_status == 'unpaid':
            amount_paid = 0.0
            online_paid = 0.0
            cash_paid = 0.0
        else:
            amount_paid = round(online_paid + cash_paid, 2)
            if amount_paid <= 0:
                flash('For partially paid invoice, enter online/cash received amount.', 'error')
                return redirect(request.url)
            if amount_paid >= total:
                payment_status = 'paid'
                amount_paid = total
                online_paid = 0.0
                cash_paid = 0.0
        balance_due = round(max(total - amount_paid, 0.0), 2)
    else:
        amount_paid = 0.0
        balance_due = 0.0
        online_paid = 0.0
        cash_paid = 0.0

    doc = {
        'id': existing_id or str(uuid.uuid4()),
        'number': doc_number,
        'doc_type': doc_type,
        'date': issue_date,
        'expiry_date': request.form.get('expiry_date', ''),
        'due_date': due_date,
        'payment_terms': payment_terms if doc_type == 'invoice' else '',
        'customer_id': cust_id,
        'place_of_supply': place_of_supply,
        'reference': request.form.get('reference', ''),
        'gst_enabled': gst_enabled,
        'use_igst': use_igst,
        'items': line_items,
        'subtotal': round(subtotal, 2),
        'total_tax': round(total_tax, 2),
        'total': total,
        'notes': request.form.get('notes', ''),
        'terms': request.form.get('terms', ''),
        'status': request.form.get('status', 'draft'),
        'payment_status': payment_status if doc_type == 'invoice' else 'unpaid',
        'amount_paid': amount_paid,
        'online_paid': online_paid,
        'cash_paid': cash_paid,
        'balance_due': balance_due,
    }

    if existing_id:
        existing_doc = next((d for d in data if d['id'] == existing_id), {})
        # Preserve integration/tracking fields
        for preserve_key in ('payment_link', 'payment_link_id', 'cf_payment_id',
                              'source_quotation', 'source_proforma', 'paid_date'):
            if preserve_key in existing_doc:
                doc[preserve_key] = existing_doc[preserve_key]
        # Overwrite the old document completely with the new one
        data = [doc if d['id'] == existing_id else d for d in data]
    else:
        data.append(doc)

    save_json(file_map[doc_type], data)
    redirect_map = {'quotation': 'quotations', 'proforma': 'proformas', 'invoice': 'invoices'}
    return redirect(url_for(redirect_map[doc_type]))


# Create folders when app starts (IMPORTANT)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LOGO_UPLOAD_DIR, exist_ok=True)
os.makedirs('static/pdfs', exist_ok=True)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
