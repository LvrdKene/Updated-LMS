import os
from datetime import datetime, timedelta
from sqlalchemy import or_
from flask import Flask, render_template, redirect, url_for, request, flash, send_file
from flask import abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import io

app = Flask(__name__)
app.config['SECRET_KEY'] = 'lab-secret-key-123' # Change this in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lab.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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
    tests = db.relationship('Test', backref='patient', lazy=True)

class Test(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    test_type = db.Column(db.String(100), nullable=False) # e.g., 'Malaria', 'FBC'
    status = db.Column(db.String(50), default='Pending') # Pending, Processing, Completed, Approved
    result_data = db.Column(db.Text, nullable=True)
    technician_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

class Inventory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    low_stock_threshold = db.Column(db.Integer, default=10)

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

# --- Helpers ---

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def log_action(action):
    log = AuditLog(action=action, user=current_user.username)
    db.session.add(log)
    db.session.commit()

# --- Routes ---

@app.route('/')
@login_required
def dashboard():
    # Dashboard stats
    # Count pending tests and include tests that have been requested to be redone
    pending_tests = Test.query.filter(Test.status.in_(['Pending', 'Redo Requested'])).count()
    completed_tests = Test.query.filter_by(status='Completed').count()
    low_stock = Inventory.query.filter(Inventory.quantity <= Inventory.low_stock_threshold).all()
    
    # Fetch recent activities for Recent Activity section
    recent_activities = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(10).all()
    
    # Prepare per-role lists
    my_tests = []
    redo_tests = []
    rejected_tests = []

    if current_user.role == 'Technician':
        # Tests assigned to this technician to process
        my_tests = Test.query.filter_by(status='Pending').all()
        # Provide redo requests that are unassigned or assigned to this technician
        redo_tests = Test.query.filter_by(status='Redo Requested').filter(
            or_(Test.technician_id == None, Test.technician_id == current_user.id)
        ).all()

    elif current_user.role == 'Admin':
        # Admin overview
        redo_tests = Test.query.filter_by(status='Redo Requested').all()
        rejected_tests = Test.query.filter_by(status='Rejected').all()

    # Others (e.g., Receptionist) get empty lists for these sections

    return render_template('dashboard.html', 
                           pending=pending_tests, 
                           completed=completed_tests, 
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
        
        # Check login attempts
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
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.password == password:
            # Successful login - reset attempts
            if attempt_record:
                db.session.delete(attempt_record)
                db.session.commit()
            
            login_user(user)
            log_action('Logged in')
            return redirect(url_for('dashboard'))
        else:
            # Failed login - increment attempts
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
        new_patient = Patient(
            name=request.form['name'],
            age=request.form['age'],
            gender=request.form['gender'],
            contact=request.form['contact']
        )
        db.session.add(new_patient)
        db.session.flush() # Get ID before commit
        
        # Create Test immediately
        new_test = Test(patient_id=new_patient.id, test_type=request.form['test_type'])
        db.session.add(new_test)
        
        db.session.commit()
        log_action(f"Registered patient {new_patient.name} and test {new_test.test_type}")
        flash('Patient and Test Registered Successfully')
        return redirect(url_for('dashboard'))
        
    return render_template('register_patient.html')

@app.route('/test_results/<int:test_id>', methods=['GET', 'POST'])
@login_required
def test_results(test_id):
    test = Test.query.get_or_404(test_id)
    
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
            # Log inventory usage for test
            inv_log = InventoryLog(
                item_name=item.item_name,
                action='used_for_test',
                quantity=1,
                user=current_user.username,
                test_id=test.id
            )
            db.session.add(inv_log)
            
        db.session.commit()
        log_action(f"Submitted results for {test.test_type} (Test ID: {test.id})")
        return redirect(url_for('dashboard'))

    return render_template('test_results.html', test=test)

@app.route('/approve_results')
@login_required
def approve_results():
    if current_user.role != 'Admin':
        return "Unauthorized", 403
    completed_tests = Test.query.filter_by(status='Completed').all()
    approved_tests = Test.query.filter_by(status='Approved').all()
    return render_template('approve_results.html', tests=completed_tests, approved_tests=approved_tests)

@app.route('/approve/<int:test_id>')
@login_required
def approve(test_id):
    if current_user.role != 'Admin': return "Unauthorized", 403
    test = Test.query.get_or_404(test_id)
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
    if request.method == 'POST':
        # Case 1: Updating Stock for existing item
        if 'item_id' in request.form:
            item = Inventory.query.get(request.form['item_id'])
            action = request.form.get('action', 'add')
            
            if action == 'delete':
                item_name = item.item_name
                item_qty = item.quantity
                db.session.delete(item)
                # Log inventory deletion
                inv_log = InventoryLog(
                    item_name=item_name,
                    action='deleted',
                    quantity=item_qty,
                    user=current_user.username
                )
                db.session.add(inv_log)
                db.session.commit()
                log_action(f"Deleted inventory item: {item_name}")
                flash(f"Deleted item: {item_name}")
            else:
                qty = int(request.form['qty'])
                
                if action == 'add':
                    item.quantity += qty
                    # Log inventory action
                    inv_log = InventoryLog(
                        item_name=item.item_name,
                        action='added',
                        quantity=qty,
                        user=current_user.username
                    )
                    db.session.add(inv_log)
                    log_action(f"Added {qty} units to {item.item_name}")
                    flash(f"Added {qty} units to {item.item_name}")
                elif action == 'reduce':
                    if item.quantity >= qty:
                        item.quantity -= qty
                        # Log inventory action
                        inv_log = InventoryLog(
                            item_name=item.item_name,
                            action='reduced',
                            quantity=qty,
                            user=current_user.username
                        )
                        db.session.add(inv_log)
                        log_action(f"Reduced {qty} units from {item.item_name}")
                        flash(f"Reduced {qty} units from {item.item_name}")
                    else:
                        flash(f"Cannot reduce! Only {item.quantity} units available.")
                        
                db.session.commit()
            
        # Case 2: Creating a NEW item
        elif 'new_item_name' in request.form:
            name = request.form['new_item_name']
            initial_qty = int(request.form['initial_qty'])
            threshold = int(request.form['threshold'])
            
            # Check if it already exists to prevent duplicates
            existing = Inventory.query.filter_by(item_name=name).first()
            if existing:
                flash('Item already exists!')
            else:
                new_item = Inventory(item_name=name, quantity=initial_qty, low_stock_threshold=threshold)
                db.session.add(new_item)
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
            if user and user.role != 'Admin':  # Prevent deleting admin
                username = user.username
                db.session.delete(user)
                db.session.commit()
                log_action(f"Deleted user: {username}")
                flash(f'User {username} deleted successfully')
            else:
                flash('Cannot delete admin account!')
    
    # Get all users including admin
    all_users = User.query.all()
    staff_users = User.query.filter(User.role != 'Admin').all()
    admin_user = User.query.filter_by(role='Admin').first()
    
    return render_template('manage_users.html', 
                          users=staff_users, 
                          admin_user=admin_user,
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

@app.route('/patient_history')
@login_required
def patient_history():
    if current_user.role not in ['Admin', 'Technician']:
        flash('Access Denied')
        return redirect(url_for('dashboard'))
    
    patients = Patient.query.order_by(Patient.id.desc()).all()
    return render_template('patient_history.html', patients=patients)

@app.route('/inventory_logs')
@login_required
def inventory_logs():
    if current_user.role != 'Admin':
        flash('Access Denied')
        return redirect(url_for('dashboard'))
    
    logs = InventoryLog.query.order_by(InventoryLog.timestamp.desc()).limit(100).all()
    return render_template('inventory_logs.html', logs=logs)

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
            patient_id = request.form.get('patient_id')
            test_id = request.form.get('test_id') if request.form.get('test_id') else None
            amount = float(request.form.get('amount'))
            payment_method = request.form.get('payment_method')
            
            new_payment = Payment(
                patient_id=patient_id,
                test_id=test_id,
                amount=amount,
                payment_method=payment_method,
                status='Pending'
            )
            db.session.add(new_payment)
            db.session.commit()
            log_action(f"Created payment record for patient ID {patient_id}")
            flash('Payment record created')
    
    # Get pending and paid payments
    pending_payments = Payment.query.filter_by(status='Pending').order_by(Payment.date_created.desc()).all()
    paid_payments = Payment.query.filter_by(status='Paid').order_by(Payment.date_confirmed.desc()).limit(50).all()
    
    # Get all patients for the payment form
    patients = Patient.query.all()
    
    return render_template('payments.html', 
                          pending_payments=pending_payments, 
                          paid_payments=paid_payments,
                          patients=patients)

@app.route('/report/<int:test_id>')
@login_required
def generate_report(test_id):
    test = Test.query.get_or_404(test_id)
    if test.status != 'Approved':
        return "Result not approved yet.", 403
    
    # Create PDF using reportlab
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor='#2c3e50',
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor='#34495e',
        spaceAfter=12
    )
    
    # Build PDF content
    story = []
    
    # Title
    story.append(Paragraph("Laboratory Test Report", title_style))
    story.append(Spacer(1, 0.3*inch))
    
    # Patient Information
    story.append(Paragraph("Patient Information", heading_style))
    story.append(Paragraph(f"<b>Name:</b> {test.patient.name}", styles['Normal']))
    story.append(Paragraph(f"<b>Age:</b> {test.patient.age}", styles['Normal']))
    story.append(Paragraph(f"<b>Gender:</b> {test.patient.gender}", styles['Normal']))
    story.append(Paragraph(f"<b>Contact:</b> {test.patient.contact or 'N/A'}", styles['Normal']))
    story.append(Spacer(1, 0.3*inch))
    
    # Test Information
    story.append(Paragraph("Test Information", heading_style))
    story.append(Paragraph(f"<b>Test Type:</b> {test.test_type}", styles['Normal']))
    story.append(Paragraph(f"<b>Status:</b> {test.status}", styles['Normal']))
    story.append(Paragraph(f"<b>Date:</b> {test.date_created.strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    story.append(Spacer(1, 0.3*inch))
    
    # Results
    story.append(Paragraph("Results", heading_style))
    story.append(Paragraph(test.result_data or "No results available", styles['Normal']))
    story.append(Spacer(1, 0.5*inch))
    
    # Footer
    story.append(Paragraph("_" * 50, styles['Normal']))
    story.append(Paragraph("This is an official laboratory report", styles['Italic']))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Result_{test.patient.name}.pdf'
    )

# --- Init DB ---
with app.app_context():
    db.create_all()
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