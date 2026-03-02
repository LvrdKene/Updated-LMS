import os
from datetime import datetime, timedelta, date
from sqlalchemy import or_, func, text, inspect
from flask import Flask, render_template, redirect, url_for, request, flash, send_file
from flask import abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing, Circle, String, Line
import io
from xml.sax.saxutils import escape
import smtplib
from email.message import EmailMessage

app = Flask(__name__)
app.config['SECRET_KEY'] = 'lab-secret-key-123' # Change this in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lab.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['LAB_NAME'] = 'Gou-LAB'
app.config['HOSPITAL_NAME'] = 'GOU-LAB'
# SMTP Configuration
app.config['SMTP_HOST'] = os.getenv('SMTP_HOST', 'smtp.gmail.com')
app.config['SMTP_PORT'] = int(os.getenv('SMTP_PORT', '587'))
app.config['SMTP_USERNAME'] = os.getenv('SMTP_USERNAME', 'ibekwekosy25@gmail.com')
app.config['SMTP_PASSWORD'] = os.getenv('SMTP_PASSWORD', 'zjnhrrsnwkyzirtg')
app.config['SMTP_USE_TLS'] = os.getenv('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
app.config['SMTP_FROM_EMAIL'] = os.getenv('SMTP_FROM_EMAIL', 'ibekwekosy25@gmail.com')
app.config['SMTP_FROM_NAME'] = os.getenv('SMTP_FROM_NAME', 'GOU-LAB')
app.config['SMTP_REPLY_TO'] = os.getenv('SMTP_REPLY_TO', 'ibekwekosy25@gmail.com')
# Optional PDF sign-off assets (absolute path or path relative to app root)
app.config['PDF_SIGNATURE_PATH'] = os.getenv('PDF_SIGNATURE_PATH', 'static/assets/signature.png')
app.config['PDF_STAMP_PATH'] = os.getenv('PDF_STAMP_PATH', 'static/assets/stamp.png')
TEST_PRICES = {
    "Full Blood Count (FBC/CBC)": 5000.0,
    "Packed Cell Volume (PCV)": 2500.0,
    "Blood Group & Rh Typing": 3000.0,
    "ESR": 2500.0,
    "Genotype (Hb Electrophoresis)": 6000.0,
    "Fasting Blood Sugar (FBS)": 3500.0,
    "Liver Function Test (LFT)": 8000.0,
    "Kidney Function Test (E/U/Cr)": 8000.0,
    "Lipid Profile (Cholesterol)": 9000.0,
    "HbA1c (Diabetes Monitoring)": 7000.0,
    "Malaria Parasite (MP)": 2500.0,
    "Widal Test (Typhoid)": 3000.0,
    "Urinalysis (Dipstick & Microscopy)": 3000.0,
    "Hepatitis B (HBsAg)": 4000.0,
    "HIV 1 & 2 Screen": 4500.0,
    "Stool Analysis": 3500.0,
}
TEST_CATEGORY_MAP = {
    "Full Blood Count (FBC/CBC)": "Hematology",
    "Packed Cell Volume (PCV)": "Hematology",
    "Blood Group & Rh Typing": "Hematology",
    "ESR": "Hematology",
    "Genotype (Hb Electrophoresis)": "Hematology",
    "Fasting Blood Sugar (FBS)": "Chemistry / Metabolism",
    "Liver Function Test (LFT)": "Chemistry / Metabolism",
    "Kidney Function Test (E/U/Cr)": "Chemistry / Metabolism",
    "Lipid Profile (Cholesterol)": "Chemistry / Metabolism",
    "HbA1c (Diabetes Monitoring)": "Chemistry / Metabolism",
    "Malaria Parasite (MP)": "Microbiology / Serology",
    "Widal Test (Typhoid)": "Microbiology / Serology",
    "Urinalysis (Dipstick & Microscopy)": "Microbiology / Serology",
    "Hepatitis B (HBsAg)": "Microbiology / Serology",
    "HIV 1 & 2 Screen": "Microbiology / Serology",
    "Stool Analysis": "Microbiology / Serology",
}

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Database Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False) # In prod, hash this!
    role = db.Column(db.String(50), nullable=False) # 'Receptionist', 'Technician', 'Admin'

class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    contact = db.Column(db.String(20))
    email = db.Column(db.String(120))
    tests = db.relationship('Test', backref='patient', lazy=True)

class Test(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    test_type = db.Column(db.String(100), nullable=False) # e.g., 'Malaria', 'FBC'
    status = db.Column(db.String(50), default='Pending') # Pending, Processing, Completed, Approved
    result_data = db.Column(db.Text, nullable=True)
    doctor_remark = db.Column(db.Text, nullable=True)
    technician_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    low_stock_threshold = db.Column(db.Integer, default=10)

class InventoryTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory.id'), nullable=False)
    item_name = db.Column(db.String(100), nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False)  # opening, add, reduce, used_for_test, delete, adjust
    quantity_delta = db.Column(db.Integer, nullable=False)  # positive for in, negative for out
    lot_number = db.Column(db.String(80), nullable=True)
    expiry_date = db.Column(db.Date, nullable=True)
    unit_cost = db.Column(db.Float, nullable=True)
    user = db.Column(db.String(100), nullable=True)
    reference = db.Column(db.String(120), nullable=True)
    note = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


def record_inventory_transaction(
    item,
    transaction_type,
    quantity_delta,
    user=None,
    lot_number=None,
    expiry_date=None,
    unit_cost=None,
    reference=None,
    note=None
):
    txn = InventoryTransaction(
        item_id=item.id,
        item_name=item.item_name,
        transaction_type=transaction_type,
        quantity_delta=quantity_delta,
        user=user,
        lot_number=lot_number,
        expiry_date=expiry_date,
        unit_cost=unit_cost,
        reference=reference,
        note=note
    )
    db.session.add(txn)


def get_fefo_lot_balances(item_id):
    lot_rows = db.session.query(
        InventoryTransaction.lot_number,
        InventoryTransaction.expiry_date,
        func.coalesce(func.sum(InventoryTransaction.quantity_delta), 0).label('balance_qty'),
        func.min(InventoryTransaction.timestamp).label('first_seen')
    ).filter(
        InventoryTransaction.item_id == item_id
    ).group_by(
        InventoryTransaction.lot_number,
        InventoryTransaction.expiry_date
    ).all()

    lots = []
    for row in lot_rows:
        balance_qty = int(row.balance_qty or 0)
        if balance_qty > 0:
            lots.append({
                'lot_number': row.lot_number,
                'expiry_date': row.expiry_date,
                'balance_qty': balance_qty,
                'first_seen': row.first_seen
            })

    # FEFO: earliest expiry first; if no expiry, consume those lots last.
    far_future = date(9999, 12, 31)
    lots.sort(key=lambda x: (x['expiry_date'] is None, x['expiry_date'] or far_future, x['first_seen']))
    return lots


def record_outflow_fefo(item, qty, transaction_type, user=None, reference=None, note=None):
    remaining = qty
    lots = get_fefo_lot_balances(item.id)

    for lot in lots:
        if remaining <= 0:
            break

        consume_qty = min(remaining, lot['balance_qty'])
        record_inventory_transaction(
            item=item,
            transaction_type=transaction_type,
            quantity_delta=-consume_qty,
            user=user,
            lot_number=lot['lot_number'],
            expiry_date=lot['expiry_date'],
            reference=reference,
            note=note
        )
        remaining -= consume_qty

    # Backward compatibility for old unlotted balances.
    if remaining > 0:
        record_inventory_transaction(
            item=item,
            transaction_type=transaction_type,
            quantity_delta=-remaining,
            user=user,
            reference=reference,
            note=note
        )

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(200), nullable=False)
    user = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class LoginAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False)
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

class InventoryLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(50), nullable=False)  # 'added', 'reduced', 'used_for_test', 'deleted'
    quantity = db.Column(db.Integer, nullable=False)
    user = db.Column(db.String(100))
    test_id = db.Column(db.Integer, nullable=True)  # If used for a test
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey('test.id'), nullable=True)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)  # 'Cash', 'Card', 'Transfer', 'Insurance'
    status = db.Column(db.String(20), default='Pending')  # 'Pending', 'Paid'
    confirmed_by = db.Column(db.String(100), nullable=True)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    date_confirmed = db.Column(db.DateTime, nullable=True)
    patient = db.relationship('Patient', backref='payments')

class PaymentTest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey('test.id'), nullable=False, unique=True)

class TestCatalog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    category = db.Column(db.String(100), nullable=False, default='General')
    price = db.Column(db.Float, nullable=False, default=0.0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

# --- Helpers ---

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def log_action(action):
    log = AuditLog(action=action, user=current_user.username)
    db.session.add(log)
    db.session.commit()

def get_test_price(test_type):
    catalog_test = TestCatalog.query.filter_by(name=test_type).first()
    if catalog_test:
        return catalog_test.price
    return TEST_PRICES.get(test_type, 0.0)

def get_paid_payment_for_test(test_id):
    paid_payment = db.session.query(Payment).join(
        PaymentTest, Payment.id == PaymentTest.payment_id
    ).filter(
        Payment.status == 'Paid',
        PaymentTest.test_id == test_id
    ).first()
    if paid_payment:
        return paid_payment
    return Payment.query.filter_by(test_id=test_id, status='Paid').first()

def get_tests_for_payment(payment):
    linked_tests = Test.query.join(PaymentTest, PaymentTest.test_id == Test.id).filter(
        PaymentTest.payment_id == payment.id
    ).all()
    if linked_tests:
        return linked_tests
    if payment.test_id:
        fallback_test = Test.query.get(payment.test_id)
        if fallback_test:
            return [fallback_test]
    return []

def get_active_tests_for_payment(payment):
    return [test for test in get_tests_for_payment(payment) if test.status != 'Cancelled']

def get_effective_payment_amount(payment):
    active_tests = get_active_tests_for_payment(payment)
    if not active_tests:
        return 0.0
    return sum(get_test_price(test.test_type) for test in active_tests)

def sync_payment_from_active_tests(payment):
    active_tests = get_active_tests_for_payment(payment)
    if not active_tests:
        return False

    payment.test_id = sorted(active_tests, key=lambda item: item.id)[0].id
    payment.amount = sum(get_test_price(test.test_type) for test in active_tests)
    return True


def load_pdf_signoff_image(path_value, width_inch, height_inch):
    if not path_value:
        return None
    normalized_path = path_value.strip()
    if not normalized_path:
        return None
    if not os.path.isabs(normalized_path):
        normalized_path = os.path.join(app.root_path, normalized_path)
    if not os.path.exists(normalized_path):
        return None
    try:
        return Image(normalized_path, width=width_inch * inch, height=height_inch * inch)
    except Exception:
        return None

def build_receipt_stamp_flowable(lab_name, size_inch=1.0):
    size = size_inch * inch
    center = size / 2
    radius = (size * 0.47)
    title = (lab_name or 'LAB').upper().strip()
    if len(title) > 22:
        title = title[:22]
    issued_stamp = datetime.utcnow().strftime('%d-%b-%Y').upper()

    drawing = Drawing(size, size)
    ink = colors.HexColor('#1e3a5f')
    soft_ink = colors.HexColor('#334e68')

    # Outer institutional ring
    drawing.add(Circle(center, center, radius, strokeColor=ink, strokeWidth=2.2, fillColor=None))
    drawing.add(Circle(center, center, radius - 4.5, strokeColor=soft_ink, strokeWidth=1.1, fillColor=None))

    # Inner emblem ring
    drawing.add(Circle(center, center, radius - 15, strokeColor=ink, strokeWidth=0.9, fillColor=None))

    # Authority lines and center insignia
    drawing.add(Line(center - 12, center, center + 12, center, strokeColor=ink, strokeWidth=1.2))
    drawing.add(Line(center, center - 12, center, center + 12, strokeColor=ink, strokeWidth=1.2))
    drawing.add(Circle(center, center, 2.2, strokeColor=ink, strokeWidth=1, fillColor=ink))

    # Top / middle / bottom legend
    drawing.add(String(center, center + 18, title, fontName='Helvetica-Bold', fontSize=6.8, textAnchor='middle', fillColor=ink))
    drawing.add(String(center, center + 7, "OFFICIAL LABORATORY SEAL", fontName='Helvetica-Bold', fontSize=5.9, textAnchor='middle', fillColor=soft_ink))
    drawing.add(String(center, center - 18, f"AUTHORIZED • {issued_stamp}", fontName='Helvetica-Bold', fontSize=5.3, textAnchor='middle', fillColor=ink))
    return drawing

def draw_report_watermark(canvas_obj, doc):
    canvas_obj.saveState()
    width, height = letter
    canvas_obj.setFillColor(colors.HexColor('#e2e8f0'))
    canvas_obj.translate(width / 2.0, height / 2.0)
    canvas_obj.rotate(35)
    canvas_obj.setFont('Helvetica-Bold', 54)
    canvas_obj.drawCentredString(0, 10, app.config.get('LAB_NAME', 'LABORATORY').upper())
    canvas_obj.setFont('Helvetica', 22)
    canvas_obj.drawCentredString(0, -28, "OFFICIAL LAB REPORT")
    canvas_obj.restoreState()

# --- Routes ---

@app.route('/')
@login_required
def dashboard():
    # Dashboard stats
    # Count pending tests and include tests that have been requested to be redone
    pending_tests = Test.query.filter(Test.status.in_(['Pending', 'Redo Requested'])).count()
    completed_tests = Test.query.filter_by(status='Completed').count()
    low_stock = Inventory.query.filter(Inventory.quantity <= Inventory.low_stock_threshold).all()
    today_revenue = 0.0
    pending_approvals = 0
    
    # Fetch recent activities for Recent Activity section
    recent_activities = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(10).all()
    
    # Prepare per-role lists
    my_tests = []
    redo_tests = []
    rejected_tests = []

    if current_user.role == 'Technician':
        # Tests assigned to this technician to process
        paid_grouped_test_ids = db.session.query(PaymentTest.test_id).join(
            Payment, Payment.id == PaymentTest.payment_id
        ).filter(
            Payment.status == 'Paid',
            PaymentTest.test_id.isnot(None)
        )
        paid_legacy_test_ids = db.session.query(Payment.test_id).filter(
            Payment.status == 'Paid',
            Payment.test_id.isnot(None)
        )
        paid_test_ids = {
            row[0] for row in paid_grouped_test_ids.union(paid_legacy_test_ids).all()
            if row and row[0] is not None
        }
        if paid_test_ids:
            my_tests = Test.query.filter_by(status='Pending').filter(Test.id.in_(paid_test_ids)).all()
        else:
            my_tests = []
        # Provide redo requests that are unassigned or assigned to this technician
        redo_tests = Test.query.filter_by(status='Redo Requested').filter(
            or_(Test.technician_id == None, Test.technician_id == current_user.id)
        ).all()

    elif current_user.role == 'Admin':
        # Admin overview
        redo_tests = Test.query.filter_by(status='Redo Requested').all()
        rejected_tests = Test.query.filter_by(status='Rejected').all()
        pending_approvals = Test.query.filter_by(status='Completed').count()
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        today_paid_candidates = Payment.query.filter(
            Payment.status == 'Paid',
            Payment.date_confirmed >= today_start,
            Payment.date_confirmed < tomorrow_start
        ).all()
        today_revenue = sum(get_effective_payment_amount(payment) for payment in today_paid_candidates)

    # Others (e.g., Receptionist) get empty lists for these sections

    return render_template('dashboard.html', 
                           pending=pending_tests, 
                           completed=completed_tests, 
                           today_revenue=today_revenue,
                           pending_approvals=pending_approvals,
                           low_stock=low_stock,
                           my_tests=my_tests,
                           redo_tests=redo_tests,
                           rejected_tests=rejected_tests,
                           recent_activities=recent_activities)


@app.route('/tests/<status>')
@login_required
def tests_by_status(status):
    # Allow only specific status views for now
    allowed = {'pending': 'Pending', 'completed': 'Completed'}
    key = status.lower()
    if key not in allowed:
        return "Not Found", 404

    desired = allowed[key]
    if desired == 'Pending':
        tests = Test.query.filter(Test.status.in_(['Pending', 'Redo Requested'])) \
            .order_by(Test.date_created.desc()).all()
    else:
        tests = Test.query.filter_by(status=desired).order_by(Test.date_created.desc()).all()

    # Attach technician username for display
    for t in tests:
        if t.technician_id:
            tech = User.query.get(t.technician_id)
            t.technician_name = tech.username if tech else 'Unknown'
        else:
            t.technician_name = 'Unassigned'

    return render_template('tests_list.html', tests=tests, status=desired)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()

        if not user:
            flash('Wrong username or password.')
            return render_template('login.html')

        # Check login attempts for existing user
        attempt_record = LoginAttempt.query.filter_by(username=username).first()
        
        if attempt_record:
            # Check if account is locked
            if attempt_record.locked_until and datetime.utcnow() < attempt_record.locked_until:
                remaining = (attempt_record.locked_until - datetime.utcnow()).seconds
                flash(f'Too many failed attempts. Please wait {remaining // 60} minutes and {remaining % 60} seconds.')
                return render_template('login.html')
            
            # Reset if lockout period has passed
            if attempt_record.locked_until and datetime.utcnow() >= attempt_record.locked_until:
                attempt_record.failed_attempts = 0
                attempt_record.locked_until = None
                db.session.commit()
        
        if user.password == password:
            # Successful login - reset attempts
            if attempt_record:
                db.session.delete(attempt_record)
                db.session.commit()
            
            login_user(user)
            log_action('Logged in')
            return redirect(url_for('dashboard'))
        else:
            # Failed login - increment attempts for existing user
            if not attempt_record:
                attempt_record = LoginAttempt(username=username, failed_attempts=1)
                db.session.add(attempt_record)
            else:
                attempt_record.failed_attempts += 1
            
            # Lock account after 5 failed attempts
            if attempt_record.failed_attempts >= 5:
                attempt_record.locked_until = datetime.utcnow() + timedelta(minutes=2)
                db.session.commit()
                flash('Too many failed attempts. Account locked for 2 minutes.')
            else:
                remaining_attempts = 5 - attempt_record.failed_attempts
                db.session.commit()
                flash(f'Wrong username or password. {remaining_attempts} attempts remaining.')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    log_action('Logged out')
    logout_user()
    return redirect(url_for('login'))

@app.route('/register_patient', methods=['GET', 'POST'])
@login_required
def register_patient():
    if current_user.role not in ['Receptionist', 'Admin']:
        flash('Access Denied')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        age_raw = request.form.get('age', '').strip()
        gender = request.form.get('gender', '').strip()

        if not name or not age_raw or not gender:
            flash('Name, age, and gender are required.')
            return redirect(url_for('register_patient'))

        try:
            age = int(age_raw)
        except ValueError:
            flash('Age must be a valid whole number.')
            return redirect(url_for('register_patient'))

        new_patient = Patient(
            name=name,
            age=age,
            gender=gender,
            contact=request.form.get('contact', '').strip(),
            email=request.form.get('email', '').strip() or None
        )
        db.session.add(new_patient)
        db.session.commit()
        log_action(f"Registered patient {new_patient.name} (ID: {new_patient.id})")
        flash('Patient registered successfully. Continue to test information.')
        return redirect(url_for('register_test_info', patient_id=new_patient.id))

    patient_search = request.args.get('patient_search', '').strip()
    patient_query = Patient.query
    if patient_search:
        like_term = f"%{patient_search}%"
        patient_filters = [
            Patient.name.ilike(like_term),
            Patient.contact.ilike(like_term),
            Patient.email.ilike(like_term)
        ]
        if patient_search.isdigit():
            patient_filters.append(Patient.id == int(patient_search))
        patient_query = patient_query.filter(or_(*patient_filters))

    patients = patient_query.order_by(Patient.id.desc()).limit(100).all()
    return render_template(
        'register_patient.html',
        patients=patients,
        patient_search=patient_search
    )


@app.route('/register_test/<int:patient_id>', methods=['GET', 'POST'])
@login_required
def register_test_info(patient_id):
    if current_user.role not in ['Receptionist', 'Admin']:
        flash('Access Denied')
        return redirect(url_for('dashboard'))

    patient = Patient.query.get_or_404(patient_id)
    active_tests = TestCatalog.query.filter_by(is_active=True).order_by(TestCatalog.category, TestCatalog.name).all()
    grouped_tests = {}
    for catalog_test in active_tests:
        grouped_tests.setdefault(catalog_test.category, []).append(catalog_test)

    if request.method == 'POST':
        selected_test_types = request.form.getlist('test_type')
        selected_test_types = [test_name.strip() for test_name in selected_test_types if test_name and test_name.strip()]

        if not selected_test_types:
            flash('Please select at least one test.')
            return redirect(url_for('register_test_info', patient_id=patient.id))

        selected_tests = TestCatalog.query.filter(
            TestCatalog.name.in_(selected_test_types),
            TestCatalog.is_active == True
        ).all()
        selected_test_lookup = {catalog_test.name: catalog_test for catalog_test in selected_tests}
        invalid_test_types = [name for name in selected_test_types if name not in selected_test_lookup]
        if invalid_test_types:
            flash('One or more selected tests are not available. Please review your selection.')
            return redirect(url_for('register_test_info', patient_id=patient.id))

        created_test_names = []
        for test_name in selected_test_types:
            db.session.add(Test(patient_id=patient.id, test_type=test_name))
            created_test_names.append(test_name)

        db.session.commit()
        log_action(f"Added tests for patient {patient.name} (ID: {patient.id}): {', '.join(created_test_names)}")
        flash(f'Test request(s) created for {patient.name}.')
        return redirect(url_for('dashboard'))

    return render_template(
        'register_test_info.html',
        patient=patient,
        grouped_tests=grouped_tests
    )

@app.route('/manage_tests', methods=['GET', 'POST'])
@login_required
def manage_tests():
    if current_user.role != 'Admin':
        flash('Access Denied')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()
            custom_category = request.form.get('custom_category', '').strip()
            if category == '__new__':
                category = custom_category
            category = category or 'General'
            price_raw = request.form.get('price', '0').strip()

            if not name:
                flash('Test name is required.')
                return redirect(url_for('manage_tests'))

            try:
                price = float(price_raw)
            except ValueError:
                flash('Price must be a valid number.')
                return redirect(url_for('manage_tests'))

            if price <= 0:
                flash('Price must be greater than zero.')
                return redirect(url_for('manage_tests'))

            existing = TestCatalog.query.filter_by(name=name).first()
            if existing:
                flash('Test already exists.')
                return redirect(url_for('manage_tests'))

            db.session.add(TestCatalog(name=name, category=category, price=price, is_active=True))
            db.session.commit()
            log_action(f"Added test catalog item: {name} (₦{price:.2f})")
            flash('Test added successfully.')
            return redirect(url_for('manage_tests'))

        if action == 'toggle':
            test_id = request.form.get('test_id')
            catalog_test = TestCatalog.query.get(test_id)
            if not catalog_test:
                flash('Test not found.')
                return redirect(url_for('manage_tests'))

            catalog_test.is_active = not catalog_test.is_active
            db.session.commit()
            status_label = 'activated' if catalog_test.is_active else 'deactivated'
            log_action(f"{status_label.title()} test catalog item: {catalog_test.name}")
            flash(f'Test {status_label}.')
            return redirect(url_for('manage_tests'))

        if action == 'delete':
            test_id = request.form.get('test_id')
            catalog_test = TestCatalog.query.get(test_id)
            if not catalog_test:
                flash('Test not found.')
                return redirect(url_for('manage_tests'))

            linked_test = Test.query.filter_by(test_type=catalog_test.name).first()
            if linked_test:
                flash('Cannot delete this test because it already has patient records. Deactivate it instead.')
                return redirect(url_for('manage_tests'))

            deleted_name = catalog_test.name
            db.session.delete(catalog_test)
            db.session.commit()
            log_action(f"Deleted test catalog item: {deleted_name}")
            flash('Test deleted successfully.')
            return redirect(url_for('manage_tests'))

        if action == 'update_price':
            test_id = request.form.get('test_id')
            new_price_raw = request.form.get('new_price', '').strip()
            catalog_test = TestCatalog.query.get(test_id)
            if not catalog_test:
                flash('Test not found.')
                return redirect(url_for('manage_tests'))

            try:
                new_price = float(new_price_raw)
            except ValueError:
                flash('Price must be a valid number.')
                return redirect(url_for('manage_tests'))

            if new_price <= 0:
                flash('Price must be greater than zero.')
                return redirect(url_for('manage_tests'))

            old_price = catalog_test.price
            catalog_test.price = new_price
            db.session.commit()
            log_action(
                f"Updated price for {catalog_test.name}: ₦{old_price:.2f} -> ₦{new_price:.2f}"
            )
            flash(f'Updated price for {catalog_test.name}.')
            return redirect(url_for('manage_tests'))

    catalog_tests = TestCatalog.query.order_by(TestCatalog.category, TestCatalog.name).all()
    categories = [row[0] for row in db.session.query(TestCatalog.category).distinct().order_by(TestCatalog.category).all()]
    return render_template('manage_tests.html', catalog_tests=catalog_tests, categories=categories)

@app.route('/test_results/<int:test_id>', methods=['GET', 'POST'])
@login_required
def test_results(test_id):
    test = Test.query.get_or_404(test_id)
    processable_statuses = {'Pending', 'Redo Requested', 'Processing'}

    if current_user.role not in ['Technician', 'Admin']:
        return "Unauthorized", 403

    if test.status not in processable_statuses:
        flash(f'This test cannot be processed because it is currently "{test.status}".')
        return redirect(url_for('dashboard'))

    if current_user.role == 'Technician':
        paid_payment = get_paid_payment_for_test(test.id)
        if not paid_payment:
            flash('Payment must be confirmed before a technician can process this test.')
            return redirect(url_for('dashboard'))
    
    if request.method == 'POST' and current_user.role in ['Technician', 'Admin']:
        test.result_data = request.form['result']
        test.status = 'Completed'
        test.technician_id = current_user.id
        
        # --- SMART INVENTORY DEDUCTION ---
        # Logic: Find a reagent that matches the test category or generic supplies
        if "Blood" in test.test_type:
            item = Inventory.query.filter_by(item_name='EDTA Tubes').first()
        elif "Malaria" in test.test_type or "Widal" in test.test_type:
            item = Inventory.query.filter_by(item_name='Reagent Kit').first()
        else:
            item = Inventory.query.filter_by(item_name='Gloves').first()

        if item and item.quantity > 0:
            item.quantity -= 1
            record_outflow_fefo(
                item=item,
                qty=1,
                transaction_type='used_for_test',
                user=current_user.username,
                reference=f'Test:{test.id}',
                note=f'Auto deduction for {test.test_type}'
            )
            
        db.session.commit()
        log_action(f"Submitted results for {test.test_type} (Test ID: {test.id})")
        return redirect(url_for('dashboard'))

    return render_template('test_results.html', test=test)


@app.route('/cancel_test/<int:test_id>', methods=['POST'])
@login_required
def cancel_test(test_id):
    if current_user.role not in ['Technician', 'Admin']:
        return "Unauthorized", 403

    test = Test.query.get_or_404(test_id)
    cancellable_statuses = {'Pending', 'Redo Requested', 'Processing'}
    if test.status not in cancellable_statuses:
        flash(f'Test cannot be cancelled because it is currently "{test.status}".')
        return redirect(url_for('dashboard'))

    if current_user.role == 'Technician':
        paid_payment = get_paid_payment_for_test(test.id)
        if not paid_payment:
            flash('Only paid tests can be cancelled by a technician.')
            return redirect(url_for('dashboard'))
        if test.technician_id and test.technician_id != current_user.id:
            flash('You can only cancel tests assigned to you.')
            return redirect(url_for('dashboard'))

    cancel_reason = request.form.get('cancel_reason', '').strip()
    test.status = 'Cancelled'
    test.result_data = None
    test.doctor_remark = None
    test.technician_id = current_user.id

    # Remove/update payment records so cancelled tests do not remain in active payment views.
    linked_payment_ids = {
        row[0] for row in db.session.query(PaymentTest.payment_id).filter(PaymentTest.test_id == test.id).all()
    }
    legacy_payment_ids = {
        row[0] for row in db.session.query(Payment.id).filter(Payment.test_id == test.id).all()
    }
    affected_payment_ids = linked_payment_ids.union(legacy_payment_ids)

    # Remove the explicit link for this cancelled test from grouped payments.
    PaymentTest.query.filter_by(test_id=test.id).delete(synchronize_session=False)

    for payment_id in affected_payment_ids:
        payment = Payment.query.get(payment_id)
        if not payment:
            continue

        payment_tests = get_tests_for_payment(payment)
        active_payment_tests = [t for t in payment_tests if t.status != 'Cancelled']

        if not active_payment_tests:
            if payment.status == 'Pending':
                db.session.delete(payment)
                log_action(f"Deleted pending payment #{payment_id} after test cancellation.")
            else:
                payment.status = 'Cancelled'
                payment.amount = 0.0
                log_action(f"Marked paid payment #{payment_id} as cancelled after test cancellation.")
            continue

        # Keep grouped/legacy anchor in sync for receipts and back-compat.
        sync_payment_from_active_tests(payment)

    db.session.commit()

    reason_suffix = f" | Reason: {cancel_reason}" if cancel_reason else ""
    log_action(f"Cancelled test ID {test.id} ({test.test_type}) for patient {test.patient.name}{reason_suffix}")
    flash(f'Test "{test.test_type}" for {test.patient.name} was cancelled.')
    return redirect(url_for('dashboard'))

@app.route('/approve_results')
@login_required
def approve_results():
    if current_user.role != 'Admin':
        return "Unauthorized", 403
    completed_tests = Test.query.filter_by(status='Completed').all()

    approved_search = request.args.get('approved_search', '').strip()
    approved_test_type = request.args.get('approved_test_type', '').strip()
    approved_date_from = request.args.get('approved_date_from', '').strip()
    approved_date_to = request.args.get('approved_date_to', '').strip()

    approved_query = Test.query.filter_by(status='Approved').join(Patient)

    if approved_search:
        like_term = f"%{approved_search}%"
        approved_query = approved_query.filter(or_(
            Patient.name.ilike(like_term),
            Test.test_type.ilike(like_term),
            Test.result_data.ilike(like_term)
        ))

    if approved_test_type:
        approved_query = approved_query.filter(Test.test_type == approved_test_type)

    if approved_date_from:
        try:
            from_dt = datetime.strptime(approved_date_from, '%Y-%m-%d')
            approved_query = approved_query.filter(Test.date_created >= from_dt)
        except ValueError:
            flash('Invalid "from" date format for approved report filter.')

    if approved_date_to:
        try:
            to_dt = datetime.strptime(approved_date_to, '%Y-%m-%d') + timedelta(days=1)
            approved_query = approved_query.filter(Test.date_created < to_dt)
        except ValueError:
            flash('Invalid "to" date format for approved report filter.')

    approved_tests = approved_query.order_by(Test.date_created.desc()).all()
    approved_sessions_map = {}
    for approved_test in approved_tests:
        session_payment = db.session.query(Payment).join(
            PaymentTest, Payment.id == PaymentTest.payment_id
        ).filter(
            PaymentTest.test_id == approved_test.id
        ).order_by(Payment.id.desc()).first()
        if not session_payment and approved_test.id:
            session_payment = Payment.query.filter_by(test_id=approved_test.id).order_by(Payment.id.desc()).first()

        if session_payment:
            session_key = f"payment-{session_payment.id}"
        else:
            session_key = f"single-{approved_test.id}"

        if session_key not in approved_sessions_map:
            approved_sessions_map[session_key] = {
                'session_key': session_key,
                'report_test_id': approved_test.id,
                'patient': approved_test.patient,
                'email': approved_test.patient.email,
                'tests': [],
                'approval_date': approved_test.date_created
            }

        approved_sessions_map[session_key]['tests'].append(approved_test)
        if approved_test.date_created > approved_sessions_map[session_key]['approval_date']:
            approved_sessions_map[session_key]['approval_date'] = approved_test.date_created

    approved_sessions = list(approved_sessions_map.values())
    approved_sessions.sort(key=lambda item: item['approval_date'], reverse=True)
    approved_test_types = [
        row[0] for row in db.session.query(Test.test_type)
        .filter(Test.status == 'Approved')
        .distinct()
        .order_by(Test.test_type)
        .all()
    ]

    return render_template(
        'approve_results.html',
        tests=completed_tests,
        approved_tests=approved_tests,
        approved_sessions=approved_sessions,
        approved_search=approved_search,
        approved_test_type=approved_test_type,
        approved_date_from=approved_date_from,
        approved_date_to=approved_date_to,
        approved_test_types=approved_test_types
    )

@app.route('/approve/<int:test_id>', methods=['POST'])
@login_required
def approve(test_id):
    if current_user.role != 'Admin': return "Unauthorized", 403
    test = Test.query.get_or_404(test_id)
    remark = request.form.get('doctor_remark', '').strip()
    if not remark:
        flash('Doctor remark is required before approval.')
        return redirect(url_for('approve_results'))

    test.doctor_remark = remark
    test.status = 'Approved'
    db.session.commit()
    return redirect(url_for('approve_results'))


@app.route('/request_redo/<int:test_id>')
@login_required
def request_redo(test_id):
    if current_user.role != 'Admin': return "Unauthorized", 403
    test = Test.query.get_or_404(test_id)
    # Mark the test so technicians know it needs re-doing
    test.status = 'Redo Requested'
    # Optionally clear technician assignment so it can be reassigned
    test.technician_id = None
    db.session.commit()
    log_action(f"Requested redo for Test ID: {test.id} ({test.test_type})")
    flash(f'Redo requested for {test.patient.name}')
    return redirect(url_for('approve_results'))

@app.route('/inventory', methods=['GET', 'POST'])
@login_required
def inventory():
    if current_user.role != 'Admin':
        flash('Access Denied')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # Case 1: Updating Stock for existing item
        if 'item_id' in request.form:
            item_id = request.form.get('item_id')
            item = Inventory.query.get(item_id)
            if not item:
                flash('Inventory item not found.')
                return redirect(url_for('inventory'))
            action = request.form.get('action', 'add')
            lot_number = request.form.get('lot_number', '').strip() or None
            expiry_date_raw = request.form.get('expiry_date', '').strip()
            unit_cost_raw = request.form.get('unit_cost', '').strip()

            expiry_date = None
            if expiry_date_raw:
                try:
                    expiry_date = datetime.strptime(expiry_date_raw, '%Y-%m-%d').date()
                except ValueError:
                    flash('Invalid expiry date format. Use YYYY-MM-DD.')
                    return redirect(url_for('inventory'))

            unit_cost = None
            if unit_cost_raw:
                try:
                    unit_cost = float(unit_cost_raw)
                    if unit_cost < 0:
                        raise ValueError
                except ValueError:
                    flash('Unit cost must be a valid non-negative number.')
                    return redirect(url_for('inventory'))
            
            if action == 'delete':
                item_name = item.item_name
                item_qty = item.quantity
                record_inventory_transaction(
                    item=item,
                    transaction_type='delete',
                    quantity_delta=-item_qty,
                    user=current_user.username,
                    reference=f'Deleted item {item_name}',
                    note='Inventory item removed'
                )
                db.session.delete(item)
                db.session.commit()
                log_action(f"Deleted inventory item: {item_name}")
                flash(f"Deleted item: {item_name}")
            else:
                qty_raw = request.form.get('qty', '').strip()
                try:
                    qty = int(qty_raw)
                except ValueError:
                    flash('Quantity must be a valid whole number.')
                    return redirect(url_for('inventory'))
                if qty <= 0:
                    flash('Quantity must be greater than zero.')
                    return redirect(url_for('inventory'))
                
                if action == 'add':
                    item.quantity += qty
                    record_inventory_transaction(
                        item=item,
                        transaction_type='add',
                        quantity_delta=qty,
                        user=current_user.username,
                        lot_number=lot_number,
                        expiry_date=expiry_date,
                        unit_cost=unit_cost,
                        note='Stock added manually'
                    )
                    log_action(f"Added {qty} units to {item.item_name}")
                    flash(f"Added {qty} units to {item.item_name}")
                elif action == 'reduce':
                    if item.quantity >= qty:
                        item.quantity -= qty
                        record_outflow_fefo(
                            item=item,
                            qty=qty,
                            transaction_type='reduce',
                            user=current_user.username,
                            note='Stock reduced manually'
                        )
                        log_action(f"Reduced {qty} units from {item.item_name}")
                        flash(f"Reduced {qty} units from {item.item_name}")
                    else:
                        flash(f"Cannot reduce! Only {item.quantity} units available.")
                        
                db.session.commit()
            
        # Case 2: Creating a NEW item
        elif 'new_item_name' in request.form:
            name = request.form.get('new_item_name', '').strip()
            if not name:
                flash('Item name is required.')
                return redirect(url_for('inventory'))

            try:
                initial_qty = int(request.form.get('initial_qty', '0').strip())
                threshold = int(request.form.get('threshold', '0').strip())
            except ValueError:
                flash('Opening quantity and low stock threshold must be whole numbers.')
                return redirect(url_for('inventory'))

            if initial_qty < 0 or threshold < 0:
                flash('Opening quantity and low stock threshold cannot be negative.')
                return redirect(url_for('inventory'))

            lot_number = request.form.get('new_lot_number', '').strip() or None
            expiry_date_raw = request.form.get('new_expiry_date', '').strip()
            unit_cost_raw = request.form.get('new_unit_cost', '').strip()

            expiry_date = None
            if expiry_date_raw:
                try:
                    expiry_date = datetime.strptime(expiry_date_raw, '%Y-%m-%d').date()
                except ValueError:
                    flash('Invalid opening stock expiry date format.')
                    return redirect(url_for('inventory'))

            unit_cost = None
            if unit_cost_raw:
                try:
                    unit_cost = float(unit_cost_raw)
                    if unit_cost < 0:
                        raise ValueError
                except ValueError:
                    flash('Opening unit cost must be a valid non-negative number.')
                    return redirect(url_for('inventory'))
            
            # Check if it already exists to prevent duplicates
            existing = Inventory.query.filter_by(item_name=name).first()
            if existing:
                flash('Item already exists!')
            else:
                new_item = Inventory(item_name=name, quantity=initial_qty, low_stock_threshold=threshold)
                db.session.add(new_item)
                db.session.flush()
                if initial_qty > 0:
                    record_inventory_transaction(
                        item=new_item,
                        transaction_type='opening',
                        quantity_delta=initial_qty,
                        user=current_user.username,
                        lot_number=lot_number,
                        expiry_date=expiry_date,
                        unit_cost=unit_cost,
                        note='Opening stock'
                    )
                db.session.commit()
                log_action(f"Created new inventory item: {name}")
                flash(f"Created new item: {name}")
                
    items = Inventory.query.all()
    return render_template('inventory.html', items=items)

@app.route('/manage_users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role != 'Admin':
        flash('Access Denied')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        # Create new user
        if action == 'create':
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role')
            
            # Check if username already exists
            existing = User.query.filter_by(username=username).first()
            if existing:
                flash('Username already exists!')
            elif len(password) < 4:
                flash('Password must be at least 4 characters long')
            else:
                new_user = User(username=username, password=password, role=role)
                db.session.add(new_user)
                db.session.commit()
                log_action(f"Created new user: {username} with role {role}")
                flash(f'User {username} created successfully!')
        
        # Delete user
        elif action == 'delete':
            user_id = request.form.get('user_id')
            user = User.query.get(user_id)
            if not user:
                flash('User not found!')
            elif user.role == 'Admin':
                if user.id == current_user.id:
                    flash('You cannot delete your own admin account.')
                else:
                    admin_count = User.query.filter_by(role='Admin').count()
                    if admin_count <= 1:
                        flash('Cannot delete the last admin account!')
                    else:
                        username = user.username
                        db.session.delete(user)
                        db.session.commit()
                        log_action(f"Deleted user: {username}")
                        flash(f'User {username} deleted successfully')
            else:
                username = user.username
                db.session.delete(user)
                db.session.commit()
                log_action(f"Deleted user: {username}")
                flash(f'User {username} deleted successfully')
    
    # Get all users including admin
    all_users = User.query.all()
    staff_users = User.query.filter(User.role != 'Admin').all()
    admins = User.query.filter_by(role='Admin').all()
    
    return render_template('manage_users.html', 
                          users=staff_users, 
                          admins=admins,
                          all_users=all_users)

@app.route('/change_password/<int:user_id>', methods=['POST'])
@login_required
def change_password(user_id):
    if current_user.role != 'Admin':
        return "Unauthorized", 403
    
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if new_password != confirm_password:
        flash('Passwords do not match!')
        return redirect(url_for('manage_users'))
    
    if new_password and len(new_password) >= 4:
        user.password = new_password
        db.session.commit()
        log_action(f"Changed password for user {user.username}")
        flash(f'Password changed successfully for {user.username}')
    else:
        flash('Password must be at least 4 characters long')
    
    return redirect(url_for('manage_users'))

@app.route('/change_own_password', methods=['POST'])
@login_required
def change_own_password():
    if current_user.role != 'Admin':
        return "Unauthorized", 403

    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')

    if not current_password or not new_password or not confirm_password:
        flash('All password fields are required')
        return redirect(url_for('manage_users'))

    if current_password != current_user.password:
        flash('Current password is incorrect')
        return redirect(url_for('manage_users'))

    if new_password != confirm_password:
        flash('New passwords do not match')
        return redirect(url_for('manage_users'))

    if len(new_password) < 4:
        flash('Password must be at least 4 characters long')
        return redirect(url_for('manage_users'))

    if new_password == current_user.password:
        flash('New password must be different from current password')
        return redirect(url_for('manage_users'))

    current_user.password = new_password
    db.session.commit()
    log_action('Changed own password')
    flash('Password changed successfully')
    return redirect(url_for('manage_users'))

@app.route('/patient_history')
@login_required
def patient_history():
    if current_user.role not in ['Admin', 'Technician']:
        flash('Access Denied')
        return redirect(url_for('dashboard'))

    selected_sort = request.args.get('sort', 'newest').strip().lower()
    if selected_sort not in ['newest', 'oldest']:
        selected_sort = 'newest'

    patients = Patient.query.all()
    all_visible_tests = []
    for patient in patients:
        patient.visible_tests = [test for test in patient.tests if test.status != 'Cancelled']
        all_visible_tests.extend(patient.visible_tests)

    visible_test_ids = [test.id for test in all_visible_tests]
    grouped_payment_map = {}
    legacy_payment_map = {}

    if visible_test_ids:
        grouped_rows = db.session.query(PaymentTest.test_id, PaymentTest.payment_id).filter(
            PaymentTest.test_id.in_(visible_test_ids)
        ).all()
        grouped_payment_map = {row[0]: row[1] for row in grouped_rows}

        legacy_rows = db.session.query(Payment.test_id, Payment.id).filter(
            Payment.test_id.in_(visible_test_ids),
            Payment.test_id.isnot(None)
        ).order_by(Payment.id.desc()).all()
        for test_id, payment_id in legacy_rows:
            if test_id not in legacy_payment_map:
                legacy_payment_map[test_id] = payment_id

    for patient in patients:
        sessions_map = {}
        ordered_tests = sorted(
            patient.visible_tests,
            key=lambda item: item.date_created or datetime.min,
            reverse=True
        )
        for test in ordered_tests:
            payment_id = grouped_payment_map.get(test.id) or legacy_payment_map.get(test.id)
            session_key = f"payment-{payment_id}" if payment_id else f"single-{test.id}"

            if session_key not in sessions_map:
                sessions_map[session_key] = {
                    'session_key': session_key,
                    'payment_id': payment_id,
                    'session_date': test.date_created,
                    'tests': []
                }

            sessions_map[session_key]['tests'].append(test)
            current_session_date = sessions_map[session_key]['session_date']
            if (test.date_created or datetime.min) > (current_session_date or datetime.min):
                sessions_map[session_key]['session_date'] = test.date_created

        patient.visible_sessions = list(sessions_map.values())
        for session in patient.visible_sessions:
            session['tests'].sort(key=lambda item: item.date_created or datetime.min, reverse=True)
            session['test_count'] = len(session['tests'])
            has_pending = any(test.status in ['Pending', 'Redo Requested', 'Processing'] for test in session['tests'])
            session['badge_class'] = 'pending' if has_pending else 'approved'

        patient.visible_sessions.sort(
            key=lambda item: item['session_date'] or datetime.min,
            reverse=True
        )
        patient.latest_session_date = patient.visible_sessions[0]['session_date'] if patient.visible_sessions else None

    patients.sort(
        key=lambda patient: patient.latest_session_date or datetime.min,
        reverse=(selected_sort == 'newest')
    )
    return render_template(
        'patient_history.html',
        patients=patients,
        selected_sort=selected_sort
    )

@app.route('/inventory_logs')
@login_required
def inventory_logs():
    if current_user.role != 'Admin':
        flash('Access Denied')
        return redirect(url_for('dashboard'))

    search = request.args.get('search', '').strip()
    action_filter = request.args.get('action', '').strip()
    user_filter = request.args.get('user', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    query = InventoryTransaction.query

    if search:
        like_term = f"%{search}%"
        query = query.filter(or_(
            InventoryTransaction.item_name.ilike(like_term),
            InventoryTransaction.user.ilike(like_term),
            InventoryTransaction.transaction_type.ilike(like_term),
            InventoryTransaction.reference.ilike(like_term),
            InventoryTransaction.note.ilike(like_term),
        ))

    if action_filter:
        query = query.filter(InventoryTransaction.transaction_type == action_filter)

    if user_filter:
        query = query.filter(InventoryTransaction.user == user_filter)

    if date_from:
        try:
            start_dt = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(InventoryTransaction.timestamp >= start_dt)
        except ValueError:
            flash('Invalid start date format.')

    if date_to:
        try:
            end_dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(InventoryTransaction.timestamp < end_dt)
        except ValueError:
            flash('Invalid end date format.')

    logs = query.order_by(InventoryTransaction.timestamp.desc()).limit(300).all()
    for log in logs:
        test_id = None
        if log.reference and str(log.reference).startswith('Test:'):
            try:
                test_id = int(str(log.reference).split(':', 1)[1])
            except (ValueError, IndexError):
                test_id = None
        log.test_id = test_id

    action_options = [
        row[0] for row in db.session.query(InventoryTransaction.transaction_type)
        .distinct()
        .order_by(InventoryTransaction.transaction_type)
        .all()
    ]
    user_options = [
        row[0] for row in db.session.query(InventoryTransaction.user)
        .filter(InventoryTransaction.user.isnot(None))
        .distinct()
        .order_by(InventoryTransaction.user)
        .all()
    ]

    return render_template(
        'inventory_logs.html',
        logs=logs,
        action_options=action_options,
        user_options=user_options,
        search=search,
        selected_action=action_filter,
        selected_user=user_filter,
        date_from=date_from,
        date_to=date_to
    )

@app.route('/payments', methods=['GET', 'POST'])
@login_required
def payments():
    if current_user.role not in ['Receptionist', 'Admin']:
        flash('Access Denied')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        # Confirm payment
        if action == 'confirm':
            payment_id = request.form.get('payment_id')
            payment = Payment.query.get(payment_id)
            if payment:
                payment.status = 'Paid'
                payment.confirmed_by = current_user.username
                payment.date_confirmed = datetime.utcnow()
                db.session.commit()
                log_action(f"Confirmed payment #{payment.id} for patient {payment.patient.name}")
                flash(f'Payment confirmed for {payment.patient.name}')
        
        # Create new payment
        elif action == 'create':
            test_id_values = request.form.getlist('test_ids')
            payment_method = request.form.get('payment_method')
            selected_test_ids = []
            for raw_id in test_id_values:
                raw_id = str(raw_id).strip()
                if raw_id.isdigit():
                    selected_test_ids.append(int(raw_id))

            if not selected_test_ids:
                flash('Please select at least one test.')
                return redirect(url_for('payments'))

            selected_tests = Test.query.filter(Test.id.in_(selected_test_ids)).all()
            if len(selected_tests) != len(set(selected_test_ids)):
                flash('One or more selected tests were not found.')
                return redirect(url_for('payments'))

            patient_ids = {test.patient_id for test in selected_tests}
            if len(patient_ids) != 1:
                flash('All selected tests must belong to the same patient.')
                return redirect(url_for('payments'))

            test_ids_set = {test.id for test in selected_tests}
            linked_payment_rows = db.session.query(PaymentTest.test_id).join(
                Payment, Payment.id == PaymentTest.payment_id
            ).filter(
                Payment.status.in_(['Pending', 'Paid']),
                PaymentTest.test_id.in_(test_ids_set)
            ).all()
            linked_test_ids = {row[0] for row in linked_payment_rows}
            legacy_paid_rows = Payment.query.filter(
                Payment.status.in_(['Pending', 'Paid']),
                Payment.test_id.in_(test_ids_set)
            ).all()
            linked_test_ids.update({payment.test_id for payment in legacy_paid_rows if payment.test_id is not None})
            if linked_test_ids:
                flash(f"Payment already exists for test ID(s): {', '.join(str(tid) for tid in sorted(linked_test_ids))}.")
                return redirect(url_for('payments'))

            total_amount = 0.0
            for selected_test in selected_tests:
                if selected_test.status not in ['Pending', 'Completed', 'Approved']:
                    flash('Payment can only be created for pending, completed, or approved tests.')
                    return redirect(url_for('payments'))
                test_price = get_test_price(selected_test.test_type)
                if test_price <= 0:
                    flash(f'No fixed price set for "{selected_test.test_type}".')
                    return redirect(url_for('payments'))
                total_amount += test_price

            anchor_test = sorted(selected_tests, key=lambda item: item.id)[0]
            new_payment = Payment(
                patient_id=anchor_test.patient_id,
                test_id=anchor_test.id,
                amount=total_amount,
                payment_method=payment_method,
                status='Pending'
            )
            db.session.add(new_payment)
            db.session.flush()

            for selected_test in selected_tests:
                db.session.add(PaymentTest(payment_id=new_payment.id, test_id=selected_test.id))

            db.session.commit()
            log_action(
                f"Created grouped payment #{new_payment.id} for patient {new_payment.patient_id}: "
                f"{len(selected_tests)} test(s), ₦{total_amount:.2f}"
            )
            flash(f'Payment record created for {len(selected_tests)} test(s) - ₦{total_amount:.2f}')
    
    # Reconcile active links/amounts before showing payment metrics.
    payment_rows_to_sync = Payment.query.filter(Payment.status.in_(['Pending', 'Paid'])).all()
    changed_payment_rows = False
    for payment in payment_rows_to_sync:
        active_tests = get_active_tests_for_payment(payment)
        if not active_tests:
            continue
        computed_amount = sum(get_test_price(test.test_type) for test in active_tests)
        anchor_test_id = sorted(active_tests, key=lambda item: item.id)[0].id
        if payment.amount != computed_amount or payment.test_id != anchor_test_id:
            payment.amount = computed_amount
            payment.test_id = anchor_test_id
            changed_payment_rows = True
    if changed_payment_rows:
        db.session.commit()

    # Daily revenue (filterable by date)
    revenue_date_str = request.args.get('revenue_date', datetime.utcnow().strftime('%Y-%m-%d'))
    try:
        revenue_date = datetime.strptime(revenue_date_str, '%Y-%m-%d')
    except ValueError:
        revenue_date = datetime.utcnow()
        revenue_date_str = revenue_date.strftime('%Y-%m-%d')

    day_start = revenue_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    daily_paid_candidates = Payment.query.filter(
        Payment.status == 'Paid',
        Payment.date_confirmed >= day_start,
        Payment.date_confirmed < day_end
    ).all()
    daily_paid_valid = [payment for payment in daily_paid_candidates if get_active_tests_for_payment(payment)]
    daily_revenue_total = sum(get_effective_payment_amount(payment) for payment in daily_paid_valid)
    daily_revenue_count = len(daily_paid_valid)

    # Get pending and paid payments
    pending_candidates = Payment.query.filter_by(status='Pending').order_by(Payment.date_created.desc()).all()
    pending_payments = [payment for payment in pending_candidates if get_active_tests_for_payment(payment)]
    payment_methods = ['Cash', 'Card', 'Transfer', 'Insurance']
    selected_paid_method = request.args.get('paid_method', 'All')
    payment_search = request.args.get('payment_search', '').strip()
    paid_date_from = request.args.get('paid_date_from', '').strip()
    paid_date_to = request.args.get('paid_date_to', '').strip()

    paid_query = Payment.query.join(Patient).filter(Payment.status == 'Paid')
    if selected_paid_method in payment_methods:
        paid_query = paid_query.filter(Payment.payment_method == selected_paid_method)

    if payment_search:
        like_term = f"%{payment_search}%"
        paid_search_filters = [
            Patient.name.ilike(like_term),
            Payment.payment_method.ilike(like_term),
            Payment.confirmed_by.ilike(like_term)
        ]
        if payment_search.isdigit():
            paid_search_filters.append(Payment.id == int(payment_search))
        paid_query = paid_query.filter(or_(*paid_search_filters))

    if paid_date_from:
        try:
            paid_from_dt = datetime.strptime(paid_date_from, '%Y-%m-%d')
            paid_query = paid_query.filter(Payment.date_confirmed >= paid_from_dt)
        except ValueError:
            flash('Invalid paid "from" date format.')

    if paid_date_to:
        try:
            paid_to_dt = datetime.strptime(paid_date_to, '%Y-%m-%d') + timedelta(days=1)
            paid_query = paid_query.filter(Payment.date_confirmed < paid_to_dt)
        except ValueError:
            flash('Invalid paid "to" date format.')

    paid_candidates = paid_query.order_by(Payment.date_confirmed.desc()).limit(50).all()
    paid_payments = [payment for payment in paid_candidates if get_active_tests_for_payment(payment)]
    
    payable_tests = Test.query.filter(Test.status.in_(['Pending', 'Completed', 'Approved'])) \
        .order_by(Test.date_created.desc()).all()

    linked_payment_rows = db.session.query(PaymentTest.test_id).join(
        Payment, Payment.id == PaymentTest.payment_id
    ).filter(
        Payment.status.in_(['Pending', 'Paid'])
    ).all()
    linked_paid_test_ids = {row[0] for row in linked_payment_rows}
    legacy_paid_test_ids = {
        row[0] for row in db.session.query(Payment.test_id).filter(
            Payment.status.in_(['Pending', 'Paid']),
            Payment.test_id.isnot(None)
        ).all()
    }
    excluded_test_ids = linked_paid_test_ids.union(legacy_paid_test_ids)

    filtered_tests = []
    for test in payable_tests:
        if test.id not in excluded_test_ids:
            filtered_tests.append(test)
    payable_test_prices = {test.test_type: get_test_price(test.test_type) for test in filtered_tests}
    
    return render_template('payments.html', 
                          pending_payments=pending_payments, 
                          paid_payments=paid_payments,
                          payable_tests=filtered_tests,
                          test_prices=payable_test_prices,
                          payment_methods=payment_methods,
                          selected_paid_method=selected_paid_method,
                          payment_search=payment_search,
                          paid_date_from=paid_date_from,
                          paid_date_to=paid_date_to,
                          revenue_date=revenue_date_str,
                          daily_revenue_total=daily_revenue_total,
                          daily_revenue_count=daily_revenue_count)

@app.route('/payment_receipt/<int:payment_id>')
@login_required
def payment_receipt(payment_id):
    if current_user.role not in ['Receptionist', 'Admin']:
        return "Unauthorized", 403

    payment = Payment.query.get_or_404(payment_id)
    if payment.status != 'Paid':
        return "Receipt available only for paid payments.", 400

    linked_tests = Test.query.join(PaymentTest, PaymentTest.test_id == Test.id).filter(
        PaymentTest.payment_id == payment.id
    ).order_by(Test.id.asc()).all()
    if not linked_tests and payment.test_id:
        fallback_test = Test.query.get(payment.test_id)
        if fallback_test:
            linked_tests = [fallback_test]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch
    )
    styles = getSampleStyleSheet()

    primary_color = '#0f172a'
    label_color = '#334155'
    accent_color = '#14532d'

    currency_font = 'Helvetica'
    unicode_font_name = 'LMSUnicode'
    unicode_font_candidates = [
        r'C:\Windows\Fonts\arial.ttf',
        r'C:\Windows\Fonts\segoeui.ttf',
        r'C:\Windows\Fonts\calibri.ttf'
    ]
    if unicode_font_name not in pdfmetrics.getRegisteredFontNames():
        for font_path in unicode_font_candidates:
            if os.path.exists(font_path):
                try:
                    pdfmetrics.registerFont(TTFont(unicode_font_name, font_path))
                    currency_font = unicode_font_name
                    break
                except Exception:
                    continue
    else:
        currency_font = unicode_font_name

    def to_pdf_text(value):
        if value is None:
            return "N/A"
        return escape(str(value)).replace('\n', '<br/>')

    hospital_style = ParagraphStyle(
        'ReceiptHospitalName',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=primary_color,
        leading=22,
        alignment=TA_LEFT
    )

    title_style = ParagraphStyle(
        'ReceiptTitle',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=accent_color,
        leading=14,
        alignment=TA_LEFT
    )

    section_style = ParagraphStyle(
        'ReceiptSection',
        parent=styles['Heading3'],
        fontSize=10.5,
        textColor=primary_color,
        spaceBefore=6,
        spaceAfter=6,
        alignment=TA_LEFT
    )

    body_style = ParagraphStyle(
        'ReceiptBody',
        parent=styles['Normal'],
        fontSize=10,
        textColor=primary_color,
        leading=14
    )

    label_style = ParagraphStyle(
        'ReceiptLabel',
        parent=styles['Normal'],
        fontSize=9.5,
        textColor=label_color,
        leading=12
    )

    meta_style = ParagraphStyle(
        'ReceiptMeta',
        parent=styles['Normal'],
        fontSize=9.5,
        textColor=label_color,
        alignment=TA_RIGHT,
        leading=12
    )

    footer_style = ParagraphStyle(
        'ReceiptFooter',
        parent=styles['Normal'],
        fontSize=8.5,
        textColor='#475569',
        alignment=TA_CENTER,
        leading=11
    )

    currency_style = ParagraphStyle(
        'ReceiptCurrency',
        parent=body_style,
        fontName=currency_font,
        alignment=TA_RIGHT
    )

    currency_label_style = ParagraphStyle(
        'ReceiptCurrencyLabel',
        parent=body_style
    )

    paid_at = payment.date_confirmed.strftime('%Y-%m-%d %H:%M') if payment.date_confirmed else 'N/A'
    receipt_no = f"RC-{payment.id:06d}"
    issued_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

    story = []
    header = Table(
        [[
            Paragraph(f"<b>{to_pdf_text(app.config.get('HOSPITAL_NAME', 'Hospital'))}</b>", hospital_style),
            Paragraph(
                f"<b>Receipt No:</b> {receipt_no}<br/>"
                f"<b>Status:</b> PAID<br/>"
                f"<b>Issued:</b> {issued_at}",
                meta_style
            )
        ]],
        colWidths=[4.7 * inch, 2.2 * inch]
    )
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0)
    ]))
    story.append(header)
    story.append(Paragraph("OFFICIAL PAYMENT RECEIPT", title_style))
    story.append(Spacer(1, 0.08 * inch))
    story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#cbd5e1')))
    story.append(Spacer(1, 0.12 * inch))

    story.append(Paragraph("Billing Information", section_style))
    billing_table = Table([
        [
            Paragraph("<b>Patient Name</b>", label_style),
            Paragraph(to_pdf_text(payment.patient.name), body_style),
            Paragraph("<b>Patient ID</b>", label_style),
            Paragraph(to_pdf_text(payment.patient_id), body_style)
        ],
        [
            Paragraph("<b>Payment Method</b>", label_style),
            Paragraph(to_pdf_text(payment.payment_method), body_style),
            Paragraph("<b>Date Paid</b>", label_style),
            Paragraph(to_pdf_text(paid_at), body_style)
        ],
        [
            Paragraph("<b>Confirmed By</b>", label_style),
            Paragraph(to_pdf_text(payment.confirmed_by or "N/A"), body_style),
            Paragraph("<b>Payment ID</b>", label_style),
            Paragraph(to_pdf_text(payment.id), body_style)
        ]
    ], colWidths=[1.35 * inch, 2.4 * inch, 1.2 * inch, 1.95 * inch])
    billing_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dbe2ea')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8fafc')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f8fafc')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7)
    ]))
    story.append(billing_table)

    if linked_tests:
        story.append(Spacer(1, 0.14 * inch))
        story.append(Paragraph("Related Tests", section_style))
        test_rows = [[
            Paragraph("<b>Test ID</b>", label_style),
            Paragraph("<b>Test Type</b>", label_style),
            Paragraph("<b>Status</b>", label_style),
            Paragraph("<b>Price</b>", label_style)
        ]]
        for linked_test in linked_tests:
            test_price = get_test_price(linked_test.test_type)
            test_rows.append([
                Paragraph(to_pdf_text(linked_test.id), body_style),
                Paragraph(to_pdf_text(linked_test.test_type), body_style),
                Paragraph(to_pdf_text(linked_test.status), body_style),
                Paragraph(f"₦{test_price:,.2f}", currency_style)
            ])
        test_table = Table(test_rows, colWidths=[0.9 * inch, 3.5 * inch, 1.25 * inch, 1.55 * inch])
        test_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dbe2ea')),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
            ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7)
        ]))
        story.append(test_table)

    story.append(Spacer(1, 0.16 * inch))
    amount_table = Table([
        [Paragraph("<b>Transaction Summary</b>", label_style), ""],
        [Paragraph("Total Tests", currency_label_style), Paragraph(str(len(linked_tests)), currency_style)],
        [Paragraph("Subtotal", currency_label_style), Paragraph(f"₦{payment.amount:,.2f}", currency_style)],
        [Paragraph("Discount", currency_label_style), Paragraph("₦0.00", currency_style)],
        [Paragraph("Total Paid", currency_label_style), Paragraph(f"₦{payment.amount:,.2f}", currency_style)]
    ], colWidths=[5.2 * inch, 1.7 * inch])
    amount_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#c7d2e0')),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8fafc')),
        ('LINEABOVE', (0, 4), (-1, 4), 0.8, colors.HexColor('#94a3b8')),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7)
    ]))
    story.append(amount_table)

    story.append(Spacer(1, 0.3 * inch))
    signature_image = load_pdf_signoff_image(app.config.get('PDF_SIGNATURE_PATH', ''), 1.5, 0.55)
    stamp_image = load_pdf_signoff_image(app.config.get('PDF_STAMP_PATH', ''), 1.0, 1.0)
    if not stamp_image:
        stamp_image = build_receipt_stamp_flowable(app.config.get('LAB_NAME', 'Laboratory'), size_inch=1.0)
    signoff_table = Table([
        [Paragraph("<b>Authorized By</b>", label_style), Paragraph("<b>Date</b>", label_style), Paragraph("<b>Signature</b>", label_style), Paragraph("<b>Stamp</b>", label_style)],
        [
            Paragraph(to_pdf_text(payment.confirmed_by or "Cashier"), body_style),
            Paragraph(to_pdf_text(payment.date_confirmed.strftime('%Y-%m-%d') if payment.date_confirmed else 'N/A'), body_style),
            signature_image if signature_image else Paragraph("__________________", body_style),
            stamp_image if stamp_image else Paragraph("__________________", body_style)
        ]
    ], colWidths=[2.3 * inch, 1.5 * inch, 1.6 * inch, 1.6 * inch])
    signoff_table.setStyle(TableStyle([
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (2, 0), (3, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3)
    ]))
    story.append(signoff_table)
    story.append(Spacer(1, 0.15 * inch))
    story.append(HRFlowable(width='100%', thickness=0.8, color=colors.HexColor('#d1d5db')))
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph("This receipt is electronically generated and serves as valid proof of payment.", footer_style))
    story.append(Paragraph("Please retain this copy for your records and insurance/claims processing where applicable.", footer_style))

    doc.build(story)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Payment_Receipt_{payment.id}.pdf'
    )

def build_lab_report_pdf(test):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.55 * inch
    )
    styles = getSampleStyleSheet()

    deep_ink = '#0b1f3a'
    muted = '#64748b'
    panel_bg = '#f6f8fc'

    def to_pdf_text(value):
        if value is None:
            return "N/A"
        return escape(str(value)).replace('\n', '<br/>')

    top_lab_style = ParagraphStyle(
        'TopLabStyle',
        parent=styles['Heading1'],
        fontSize=17,
        textColor=colors.white,
        alignment=TA_LEFT,
        leading=21
    )

    top_meta_style = ParagraphStyle(
        'TopMetaStyle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.white,
        alignment=TA_RIGHT,
        leading=12
    )

    section_header_style = ParagraphStyle(
        'SectionHeaderStyle',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=deep_ink,
        spaceBefore=10,
        spaceAfter=6
    )

    field_label_style = ParagraphStyle(
        'FieldLabelStyle',
        parent=styles['Normal'],
        fontSize=8.8,
        textColor=muted,
        leading=11,
        alignment=TA_LEFT
    )

    field_value_style = ParagraphStyle(
        'FieldValueStyle',
        parent=styles['Normal'],
        fontSize=10.2,
        textColor=deep_ink,
        leading=14,
        alignment=TA_LEFT
    )

    body_text_style = ParagraphStyle(
        'BodyTextStyle',
        parent=styles['Normal'],
        fontSize=10.1,
        textColor=deep_ink,
        leading=15
    )

    footer_style = ParagraphStyle(
        'LabFooterStyle',
        parent=styles['Normal'],
        fontSize=8.5,
        textColor=muted,
        alignment=TA_CENTER,
        leading=11
    )

    report_no = f"LR-{test.id:06d}"
    issued_on = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    created_on = test.date_created.strftime('%Y-%m-%d %H:%M')
    verified_on = datetime.utcnow().strftime('%Y-%m-%d')
    session_test_count = 1
    session_payment = db.session.query(Payment).join(
        PaymentTest, Payment.id == PaymentTest.payment_id
    ).filter(
        PaymentTest.test_id == test.id
    ).order_by(Payment.id.desc()).first()
    if not session_payment and test.id:
        session_payment = Payment.query.filter_by(test_id=test.id).order_by(Payment.id.desc()).first()

    if session_payment:
        linked_count = db.session.query(func.count(PaymentTest.id)).filter(
            PaymentTest.payment_id == session_payment.id
        ).scalar() or 0
        session_test_count = int(linked_count) if linked_count > 0 else 1

    story = []

    top_banner = Table(
        [[
            Paragraph(
                f"<b>{to_pdf_text(app.config.get('LAB_NAME', 'Laboratory'))}</b><br/>"
                f"<font size='10'>Clinical Pathology and Diagnostic Services</font>",
                top_lab_style
            ),
            Paragraph(
                f"<b>LABORATORY RESULT REPORT</b><br/>"
                f"Report No: {report_no}<br/>"
                f"Issued: {issued_on}",
                top_meta_style
            )
        ]],
        colWidths=[4.8 * inch, 2.2 * inch]
    )
    top_banner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(deep_ink)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10)
    ]))
    story.append(top_banner)
    story.append(Spacer(1, 0.1 * inch))

    id_strip = Table(
        [[
            Paragraph(f"<b>Patient ID:</b> {to_pdf_text(test.patient.id)}", field_value_style),
            Paragraph(f"<b>Sample Date:</b> {to_pdf_text(created_on)}", field_value_style),
            Paragraph(f"<b>Result Status:</b> {to_pdf_text(test.status)}", field_value_style)
        ]],
        colWidths=[2.3 * inch, 2.35 * inch, 2.35 * inch]
    )
    id_strip.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eef2f9')),
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#c8d3e3')),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7)
    ]))
    story.append(id_strip)

    story.append(Paragraph("Patient Demographics", section_header_style))
    patient_grid = Table([
        [
            Paragraph("<b>Full Name</b>", field_label_style),
            Paragraph("<b>Age</b>", field_label_style),
            Paragraph("<b>Gender</b>", field_label_style),
            Paragraph("<b>Contact</b>", field_label_style)
        ],
        [
            Paragraph(to_pdf_text(test.patient.name), field_value_style),
            Paragraph(to_pdf_text(test.patient.age), field_value_style),
            Paragraph(to_pdf_text(test.patient.gender), field_value_style),
            Paragraph(to_pdf_text(test.patient.contact or "N/A"), field_value_style)
        ]
    ], colWidths=[3.15 * inch, 1.0 * inch, 1.0 * inch, 1.85 * inch])
    patient_grid.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(panel_bg)),
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#d5deea')),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6)
    ]))
    story.append(patient_grid)

    story.append(Paragraph("Requested Investigation", section_header_style))
    investigation = Table([
        [Paragraph("<b>Test Name</b>", field_label_style), Paragraph(to_pdf_text(test.test_type), field_value_style)],
        [Paragraph("<b>Verified On</b>", field_label_style), Paragraph(to_pdf_text(verified_on), field_value_style)],
        [Paragraph("<b>Total Tests (Session)</b>", field_label_style), Paragraph(to_pdf_text(session_test_count), field_value_style)]
    ], colWidths=[1.6 * inch, 5.4 * inch])
    investigation.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor(panel_bg)),
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#d5deea')),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6)
    ]))
    story.append(investigation)

    story.append(Paragraph("Laboratory Findings", section_header_style))
    findings_card = Table(
        [[Paragraph(to_pdf_text(test.result_data or "No results available"), body_text_style)]],
        colWidths=[7.0 * inch]
    )
    findings_card.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('BOX', (0, 0), (-1, -1), 1.0, colors.HexColor('#c6d3e6')),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12)
    ]))
    story.append(findings_card)

    if test.doctor_remark:
        story.append(Paragraph("Clinical Remark", section_header_style))
        remark_card = Table(
            [[Paragraph(to_pdf_text(test.doctor_remark), body_text_style)]],
            colWidths=[7.0 * inch]
        )
        remark_card.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fefce8')),
            ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#e2cf93')),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10)
        ]))
        story.append(remark_card)

    report_signature_image = load_pdf_signoff_image(app.config.get('PDF_SIGNATURE_PATH', ''), 1.5, 0.55)
    report_stamp_image = load_pdf_signoff_image(app.config.get('PDF_STAMP_PATH', ''), 0.95, 0.95)
    if not report_stamp_image:
        report_stamp_image = build_receipt_stamp_flowable(app.config.get('LAB_NAME', 'Laboratory'), size_inch=0.95)
    signoff_parts = []
    if report_signature_image:
        signoff_parts.append(report_signature_image)
    else:
        signoff_parts.append(Paragraph("__________________", field_value_style))
    signoff_parts.append(Spacer(1, 0.05 * inch))
    if report_stamp_image:
        signoff_parts.append(report_stamp_image)
    else:
        signoff_parts.append(Paragraph("[STAMP]", field_label_style))

    story.append(Spacer(1, 0.26 * inch))
    authorization = Table([
        [
            Paragraph("<b>Verified By</b>", field_label_style),
            Paragraph("<b>Designation</b>", field_label_style),
            Paragraph("<b>Signature / Stamp</b>", field_label_style)
        ],
        [
            Paragraph("Lab Administrator", field_value_style),
            Paragraph("Authorized Signatory", field_value_style),
            signoff_parts
        ]
    ], colWidths=[2.2 * inch, 2.3 * inch, 2.5 * inch])
    authorization.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(panel_bg)),
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#d5deea')),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6)
    ]))
    story.append(authorization)

    story.append(Spacer(1, 0.13 * inch))
    story.append(HRFlowable(width='100%', thickness=0.8, color=colors.HexColor('#d1d9e6')))
    story.append(Spacer(1, 0.07 * inch))
    story.append(Paragraph("This report is confidential and intended solely for clinical use by authorized healthcare professionals.", footer_style))
    story.append(Paragraph("Please interpret findings in conjunction with patient symptoms, history, and other diagnostic tests.", footer_style))

    doc.build(
        story,
        onFirstPage=draw_report_watermark,
        onLaterPages=draw_report_watermark
    )
    buffer.seek(0)
    return buffer


def get_report_session_tests(test):
    session_payment = db.session.query(Payment).join(
        PaymentTest, Payment.id == PaymentTest.payment_id
    ).filter(
        PaymentTest.test_id == test.id
    ).order_by(Payment.id.desc()).first()
    if not session_payment and test.id:
        session_payment = Payment.query.filter_by(test_id=test.id).order_by(Payment.id.desc()).first()

    if session_payment:
        session_tests = Test.query.join(
            PaymentTest, PaymentTest.test_id == Test.id
        ).filter(
            PaymentTest.payment_id == session_payment.id,
            Test.status == 'Approved'
        ).order_by(Test.id.asc()).all()
        if session_tests:
            return session_tests
    return [test]


def build_session_lab_report_pdf(primary_test, session_tests):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.55 * inch
    )
    styles = getSampleStyleSheet()
    deep_ink = '#0b1f3a'
    muted = '#64748b'
    panel_bg = '#f6f8fc'

    def to_pdf_text(value):
        if value is None:
            return "N/A"
        return escape(str(value)).replace('\n', '<br/>')

    top_lab_style = ParagraphStyle(
        'TopLabStyleSession',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.white,
        alignment=TA_LEFT,
        leading=20
    )
    top_meta_style = ParagraphStyle(
        'TopMetaStyleSession',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.white,
        alignment=TA_RIGHT,
        leading=12
    )
    section_header_style = ParagraphStyle(
        'SectionHeaderStyleSession',
        parent=styles['Heading3'],
        fontSize=11,
        textColor=deep_ink,
        spaceBefore=10,
        spaceAfter=6
    )
    field_label_style = ParagraphStyle(
        'FieldLabelStyleSession',
        parent=styles['Normal'],
        fontSize=8.8,
        textColor=muted,
        leading=11
    )
    field_value_style = ParagraphStyle(
        'FieldValueStyleSession',
        parent=styles['Normal'],
        fontSize=10,
        textColor=deep_ink,
        leading=14
    )
    body_text_style = ParagraphStyle(
        'BodyTextStyleSession',
        parent=styles['Normal'],
        fontSize=9.8,
        textColor=deep_ink,
        leading=14
    )
    footer_style = ParagraphStyle(
        'LabFooterStyleSession',
        parent=styles['Normal'],
        fontSize=8.5,
        textColor=muted,
        alignment=TA_CENTER,
        leading=11
    )

    first_test = session_tests[0]
    report_no = f"LRS-{primary_test.id:06d}"
    issued_on = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

    story = []

    top_banner = Table(
        [[
            Paragraph(
                f"<b>{to_pdf_text(app.config.get('LAB_NAME', 'Laboratory'))}</b><br/>"
                f"<font size='10'>Clinical Pathology and Diagnostic Services</font>",
                top_lab_style
            ),
            Paragraph(
                f"<b>LABORATORY SESSION REPORT</b><br/>"
                f"Report No: {report_no}<br/>"
                f"Issued: {issued_on}",
                top_meta_style
            )
        ]],
        colWidths=[4.8 * inch, 2.2 * inch]
    )
    top_banner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(deep_ink)),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10)
    ]))
    story.append(top_banner)
    story.append(Spacer(1, 0.1 * inch))

    story.append(Paragraph("Patient Demographics", section_header_style))
    patient_grid = Table([
        [
            Paragraph("<b>Full Name</b>", field_label_style),
            Paragraph("<b>Age</b>", field_label_style),
            Paragraph("<b>Gender</b>", field_label_style),
            Paragraph("<b>Contact</b>", field_label_style)
        ],
        [
            Paragraph(to_pdf_text(primary_test.patient.name), field_value_style),
            Paragraph(to_pdf_text(primary_test.patient.age), field_value_style),
            Paragraph(to_pdf_text(primary_test.patient.gender), field_value_style),
            Paragraph(to_pdf_text(primary_test.patient.contact or "N/A"), field_value_style)
        ]
    ], colWidths=[3.15 * inch, 1.0 * inch, 1.0 * inch, 1.85 * inch])
    patient_grid.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(panel_bg)),
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#d5deea')),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6)
    ]))
    story.append(patient_grid)

    story.append(Paragraph("Session Summary", section_header_style))
    session_table = Table([
        [Paragraph("<b>Total Tests (Session)</b>", field_label_style), Paragraph(to_pdf_text(len(session_tests)), field_value_style)],
        [Paragraph("<b>Session Date</b>", field_label_style), Paragraph(to_pdf_text(first_test.date_created.strftime('%Y-%m-%d %H:%M')), field_value_style)]
    ], colWidths=[1.8 * inch, 5.2 * inch])
    session_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor(panel_bg)),
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#d5deea')),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6)
    ]))
    story.append(session_table)

    story.append(Paragraph("Investigations & Findings", section_header_style))
    for index, session_test in enumerate(session_tests, start=1):
        story.append(Paragraph(
            f"<b>{index}. {to_pdf_text(session_test.test_type)}</b> "
            f"<font color='{muted}'>({to_pdf_text(session_test.date_created.strftime('%Y-%m-%d %H:%M'))})</font>",
            field_value_style
        ))
        findings_card = Table(
            [[Paragraph(to_pdf_text(session_test.result_data or "No results available"), body_text_style)]],
            colWidths=[7.0 * inch]
        )
        findings_card.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.white),
            ('BOX', (0, 0), (-1, -1), 0.9, colors.HexColor('#c6d3e6')),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 9)
        ]))
        story.append(findings_card)
        if session_test.doctor_remark:
            remark_card = Table(
                [[Paragraph(f"<b>Clinical Remark:</b> {to_pdf_text(session_test.doctor_remark)}", body_text_style)]],
                colWidths=[7.0 * inch]
            )
            remark_card.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fefce8')),
                ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#e2cf93')),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8)
            ]))
            story.append(remark_card)
        story.append(Spacer(1, 0.08 * inch))

    session_signature_image = load_pdf_signoff_image(app.config.get('PDF_SIGNATURE_PATH', ''), 1.5, 0.55)
    session_stamp_image = load_pdf_signoff_image(app.config.get('PDF_STAMP_PATH', ''), 0.95, 0.95)
    if not session_stamp_image:
        session_stamp_image = build_receipt_stamp_flowable(app.config.get('LAB_NAME', 'Laboratory'), size_inch=0.95)
    session_signoff_parts = []
    if session_signature_image:
        session_signoff_parts.append(session_signature_image)
    else:
        session_signoff_parts.append(Paragraph("__________________", field_value_style))
    session_signoff_parts.append(Spacer(1, 0.05 * inch))
    if session_stamp_image:
        session_signoff_parts.append(session_stamp_image)
    else:
        session_signoff_parts.append(Paragraph("[STAMP]", field_label_style))

    story.append(Paragraph("Authorization", section_header_style))
    session_authorization = Table([
        [
            Paragraph("<b>Verified By</b>", field_label_style),
            Paragraph("<b>Designation</b>", field_label_style),
            Paragraph("<b>Signature / Stamp</b>", field_label_style)
        ],
        [
            Paragraph("Lab Administrator", field_value_style),
            Paragraph("Authorized Signatory", field_value_style),
            session_signoff_parts
        ]
    ], colWidths=[2.2 * inch, 2.3 * inch, 2.5 * inch])
    session_authorization.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(panel_bg)),
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#d5deea')),
        ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dce5f0')),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
    ]))
    story.append(session_authorization)

    story.append(Spacer(1, 0.12 * inch))
    story.append(HRFlowable(width='100%', thickness=0.8, color=colors.HexColor('#d1d9e6')))
    story.append(Spacer(1, 0.07 * inch))
    story.append(Paragraph("This report is confidential and intended solely for clinical use by authorized healthcare professionals.", footer_style))
    story.append(Paragraph("Please interpret findings in conjunction with patient symptoms, history, and other diagnostic tests.", footer_style))

    doc.build(
        story,
        onFirstPage=draw_report_watermark,
        onLaterPages=draw_report_watermark
    )
    buffer.seek(0)
    return buffer


def send_lab_report_email(test):
    smtp_host = app.config.get('SMTP_HOST', '').strip()
    smtp_port = int(app.config.get('SMTP_PORT', 587))
    smtp_username = app.config.get('SMTP_USERNAME', '').strip()
    smtp_password = app.config.get('SMTP_PASSWORD', '')
    smtp_use_tls = bool(app.config.get('SMTP_USE_TLS', True))
    from_email = app.config.get('SMTP_FROM_EMAIL', '').strip() or smtp_username
    from_name = app.config.get('SMTP_FROM_NAME', 'GOU-LAB').strip() or 'GOU-LAB'
    reply_to = app.config.get('SMTP_REPLY_TO', '').strip()

    if not smtp_host:
        return False, "SMTP_HOST is not configured."
    if not from_email:
        return False, "SMTP_FROM_EMAIL or SMTP_USERNAME must be configured."
    if not test.patient.email:
        return False, "Patient does not have a registered email address."

    session_tests = get_report_session_tests(test)
    if len(session_tests) > 1:
        report_bytes = build_session_lab_report_pdf(test, session_tests).getvalue()
    else:
        report_bytes = build_lab_report_pdf(test).getvalue()
    msg = EmailMessage()
    if len(session_tests) > 1:
        msg['Subject'] = f"Lab Session Report - {len(session_tests)} Tests (#{test.id})"
    else:
        msg['Subject'] = f"Lab Report - {test.test_type} (#{test.id})"
    msg['From'] = f"{from_name} <{from_email}>"
    msg['To'] = test.patient.email
    if reply_to:
        msg['Reply-To'] = reply_to

    patient_name = test.patient.name or "Patient"
    report_no = f"LR-{test.id:06d}" if len(session_tests) == 1 else f"LRS-{test.id:06d}"
    generated_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    investigation_line = test.test_type if len(session_tests) == 1 else f"{len(session_tests)} tests in one session"

    msg.set_content(
        f"Dear {patient_name},\n\n"
        f"Your approved laboratory report is attached as a PDF.\n\n"
        f"Report No: {report_no}\n"
        f"Investigation: {investigation_line}\n"
        f"Generated: {generated_at}\n\n"
        f"If you have questions about interpretation, please contact the laboratory.\n\n"
        f"Regards,\n{app.config.get('LAB_NAME', 'Laboratory')}"
    )

    html_body = f"""
<html>
  <body style="margin:0;padding:0;background:#f4f7fb;font-family:Arial,sans-serif;color:#0f172a;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="640" style="max-width:640px;background:#ffffff;border:1px solid #dbe5f1;border-radius:10px;overflow:hidden;">
            <tr>
              <td style="background:#0b1f3a;color:#ffffff;padding:18px 22px;">
                <div style="font-size:20px;font-weight:700;line-height:1.3;">{escape(app.config.get('LAB_NAME', 'Laboratory'))}</div>
                <div style="font-size:12px;opacity:0.9;">Clinical Pathology and Diagnostic Services</div>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 22px 8px 22px;">
                <div style="font-size:22px;font-weight:700;color:#0f172a;">Laboratory Report Notification</div>
                <div style="font-size:14px;color:#475569;margin-top:6px;">An approved report is attached to this email.</div>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 22px 0 22px;">
                <p style="margin:0 0 12px 0;font-size:15px;color:#0f172a;">Dear {escape(patient_name)},</p>
                <p style="margin:0 0 12px 0;font-size:14px;line-height:1.6;color:#334155;">
                  Your laboratory investigation has been reviewed and approved. Please find your official result report attached as a PDF document.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:6px 22px 0 22px;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border:1px solid #dbe5f1;border-radius:8px;background:#f8fbff;">
                  <tr>
                    <td style="padding:12px 14px;font-size:13px;color:#64748b;width:42%;">Report Number</td>
                    <td style="padding:12px 14px;font-size:13px;color:#0f172a;font-weight:600;">{report_no}</td>
                  </tr>
                  <tr>
                    <td style="padding:12px 14px;font-size:13px;color:#64748b;border-top:1px solid #e2e8f0;">Investigation</td>
                    <td style="padding:12px 14px;font-size:13px;color:#0f172a;font-weight:600;border-top:1px solid #e2e8f0;">{escape(investigation_line)}</td>
                  </tr>
                  <tr>
                    <td style="padding:12px 14px;font-size:13px;color:#64748b;border-top:1px solid #e2e8f0;">Generated On</td>
                    <td style="padding:12px 14px;font-size:13px;color:#0f172a;font-weight:600;border-top:1px solid #e2e8f0;">{generated_at}</td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 22px 4px 22px;">
                <p style="margin:0;font-size:13px;line-height:1.6;color:#475569;">
                  For clinical interpretation, kindly consult your healthcare provider.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 22px 22px 22px;">
                <p style="margin:0;font-size:14px;color:#0f172a;">Regards,<br><strong>{escape(app.config.get('LAB_NAME', 'Laboratory'))}</strong></p>
              </td>
            </tr>
            <tr>
              <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:12px 22px;">
                <div style="font-size:11px;color:#64748b;line-height:1.5;">
                  This is an automated message. Please do not reply directly to this email.
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    msg.add_alternative(html_body, subtype='html')

    msg.add_attachment(
        report_bytes,
        maintype='application',
        subtype='pdf',
        filename=f"Result_{test.patient.name}_{test.id}.pdf"
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            if smtp_use_tls:
                server.starttls()
            if smtp_username:
                server.login(smtp_username, smtp_password)
            server.send_message(msg)
    except Exception as exc:
        return False, f"Email delivery failed: {exc}"

    return True, "Report emailed successfully."


@app.route('/report/<int:test_id>')
@login_required
def generate_report(test_id):
    test = Test.query.get_or_404(test_id)
    if test.status != 'Approved':
        return "Result not approved yet.", 403

    session_tests = get_report_session_tests(test)
    if len(session_tests) > 1:
        buffer = build_session_lab_report_pdf(test, session_tests)
    else:
        buffer = build_lab_report_pdf(test)
    download_name = f'Result_{test.patient.name}.pdf' if len(session_tests) == 1 else f'Result_{test.patient.name}_Session.pdf'
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=download_name
    )


@app.route('/send_report_email/<int:test_id>', methods=['POST'])
@login_required
def send_report_email(test_id):
    if current_user.role != 'Admin':
        return "Unauthorized", 403

    test = Test.query.get_or_404(test_id)
    if test.status != 'Approved':
        flash('Only approved reports can be emailed.')
        return redirect(url_for('approve_results'))

    ok, message = send_lab_report_email(test)
    if ok:
        log_action(f"Emailed report for Test ID: {test.id} to {test.patient.email}")
        flash(message)
    else:
        flash(message)

    return redirect(url_for('approve_results'))

# --- Init DB ---
with app.app_context():
    db.create_all()

    # Backfill grouped payment links for existing single-test payments.
    existing_links = {row[0] for row in db.session.query(PaymentTest.test_id).all()}
    legacy_payments = Payment.query.filter(Payment.test_id.isnot(None)).all()
    for legacy_payment in legacy_payments:
        if legacy_payment.test_id not in existing_links:
            db.session.add(PaymentTest(payment_id=legacy_payment.id, test_id=legacy_payment.test_id))
            existing_links.add(legacy_payment.test_id)
    db.session.commit()

    # Lightweight schema upgrade for existing SQLite installs.
    patient_columns = {col['name'] for col in inspect(db.engine).get_columns('patient')}
    if 'email' not in patient_columns:
        db.session.execute(text("ALTER TABLE patient ADD COLUMN email VARCHAR(120)"))
        db.session.commit()

    # Backfill ledger with opening balance for existing items when table is first introduced.
    if InventoryTransaction.query.count() == 0:
        existing_items = Inventory.query.all()
        for itm in existing_items:
            if itm.quantity and itm.quantity > 0:
                db.session.add(InventoryTransaction(
                    item_id=itm.id,
                    item_name=itm.item_name,
                    transaction_type='opening',
                    quantity_delta=itm.quantity,
                    user='system',
                    note='Backfilled opening stock'
                ))
        db.session.commit()

    for test_name, price in TEST_PRICES.items():
        if not TestCatalog.query.filter_by(name=test_name).first():
            db.session.add(TestCatalog(
                name=test_name,
                category=TEST_CATEGORY_MAP.get(test_name, 'General'),
                price=price,
                is_active=True
            ))
    db.session.commit()
    # Inside the "with app.app_context():" block at the bottom
    if not Inventory.query.filter_by(item_name='EDTA Tubes').first():
        db.session.add(Inventory(item_name='EDTA Tubes', quantity=100, low_stock_threshold=20))
        db.session.add(Inventory(item_name='Microscope Slides', quantity=200, low_stock_threshold=30))
        db.session.commit()
    # Create Default Users if not exist
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', password='password', role='Admin'))
        db.session.add(User(username='tech', password='password', role='Technician'))
        db.session.add(User(username='nurse', password='password', role='Receptionist'))
        # Default Inventory
        db.session.add(Inventory(item_name='Reagent Kit', quantity=50))
        db.session.add(Inventory(item_name='Gloves', quantity=100))
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True)
