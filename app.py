# --- Imports ---
from flask import Flask, render_template, request, jsonify, redirect, url_for, make_response
import json
import os
import sys
import base64
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import auth as fb_auth, credentials
from functools import wraps
from flask_migrate import Migrate, upgrade as migrate_upgrade
from sqlalchemy import func
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from types import SimpleNamespace as NS


print("--- app.py execution started ---")
# Load environment variables first
load_dotenv()
print("DEBUG: Loaded .env file")

# --- App Initialization ---
app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return {"ok": True}

# Secret key
app.secret_key = os.getenv('FLASK_SECRET_KEY') or 'super-fallback-secret-key-not-for-production-ever'
if not os.getenv('FLASK_SECRET_KEY'):
    print("Warning: FLASK_SECRET_KEY not set. Using default for development.")

# --- Firebase Initialization ---
firebase_admin_initialized = False
auth = None
print("DEBUG: Attempting Firebase Admin SDK Initialization...")
try:
    firebase_credentials_base64 = os.getenv('FIREBASE_CREDENTIALS_BASE64')
    if firebase_credentials_base64:
        print("DEBUG: FIREBASE_CREDENTIALS_BASE64 found.")
        try:
            credentials_json_str = base64.b64decode(firebase_credentials_base64).decode('utf-8')
            print("DEBUG: Base64 decoded successfully.")
            cred_info = json.loads(credentials_json_str)
            print(f"DEBUG: JSON loaded successfully. Project ID: {cred_info.get('project_id')}")
            cred = credentials.Certificate(cred_info)
            print("DEBUG: credentials.Certificate object created.")
        except Exception as parse_error:
            print(f"ERROR during credential decoding/parsing: {type(parse_error).__name__} - {str(parse_error)}")
            raise

        if not firebase_admin._apps:
            print("DEBUG: Attempting firebase_admin.initialize_app()...")
            firebase_admin.initialize_app(cred)
            print("DEBUG: firebase_admin.initialize_app() successful.")
        else:
            print("DEBUG: Firebase Admin SDK already initialized (Skipping init).")

        auth = fb_auth
        firebase_admin_initialized = True
        print("Firebase Admin SDK initialization marked as successful.")
    else:
        print("ERROR: FIREBASE_CREDENTIALS_BASE64 environment variable not set or empty.")
except Exception as e:
    print(f"CRITICAL ERROR initializing Firebase Admin SDK: {type(e).__name__} - {str(e)}")
    firebase_admin_initialized = False
    auth = None

# --- Database Configuration (Hybrid: Connector or URL) ---
import os, json
from flask_migrate import Migrate, upgrade as migrate_upgrade

db_config_ok = False
db = None
migrate = None

USE_CONNECTOR = bool(os.getenv("INSTANCE_CONNECTION_NAME"))  # if present, prefer connector

if USE_CONNECTOR:
    # ---- Cloud SQL Python Connector path (no IP allow-listing) ----
    print("DB: Using Cloud SQL Python Connector")
# --- inside the USE_CONNECTOR block ---
    from google.cloud.sql.connector import Connector, IPTypes
    from google.oauth2 import service_account
    import base64, json

    # Prefer base64 to avoid dotenv parsing issues
    sa_b64 = os.getenv("GCP_SA_KEY_B64")
    sa_raw = os.getenv("GCP_SA_KEY")
    if sa_b64:
        sa_dict = json.loads(base64.b64decode(sa_b64))
    elif sa_raw and sa_raw.strip().startswith("{"):
        sa_dict = json.loads(sa_raw)
    else:
        raise RuntimeError("Provide GCP_SA_KEY_B64 (preferred) or GCP_SA_KEY as JSON.")

    credentials = service_account.Credentials.from_service_account_info(sa_dict)


    INSTANCE_CONNECTION_NAME = os.getenv("INSTANCE_CONNECTION_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASS = os.getenv("DB_PASS")
    DB_NAME = os.getenv("DB_NAME")

    connector = Connector(credentials=credentials)

    def getconn():
        # Returns a pg8000 DB-API connection; SQLAlchemy will use this instead of a URL socket
        conn = connector.connect(
            INSTANCE_CONNECTION_NAME,
            driver="pg8000",
            user=DB_USER,
            password=DB_PASS,
            db=DB_NAME,
            ip_type=IPTypes.PUBLIC,  # keep PUBLIC unless you’re on a private VPC
        )
        return conn

    # Configure Flask-SQLAlchemy to use the creator
    app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql+pg8000://"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "creator": getconn,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 1,
        "max_overflow": 0,
    }
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db_config_ok = True

else:
    # ---- URL path (Neon/local/Postgres/GCP Public IP) ----
    print("DB: Using URL from env (DATABASE_URL/POSTGRES_URL/POSTGRES_URL_NO_SSL)")
    database_uri = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("POSTGRES_URL_NO_SSL")
    if database_uri:
        if database_uri.startswith("postgres://"):
            database_uri = database_uri.replace("postgres://", "postgresql://", 1)
        if "sslmode=" not in database_uri:
            database_uri = f"{database_uri}{'&' if '?' in database_uri else '?'}sslmode=require"
        app.config["SQLALCHEMY_DATABASE_URI"] = database_uri
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        print("Database URI loaded from environment variable:", database_uri)
        db_config_ok = True
    else:
        print("Warning: DATABASE_URL/POSTGRES_URL not set. Database connection not configured.")

# Initialize SQLAlchemy and Flask-Migrate
if db_config_ok:
    try:
        print("DEBUG: Importing db from extensions")
        from extensions import db as _db
        db = _db
        print("DEBUG: db object from extensions =", db)
        if db is None:
            raise ValueError("db is None after import from extensions")
        db.init_app(app)
        print("SQLAlchemy initialized successfully.")
        migrate = Migrate(app, db)
        print("Flask-Migrate initialized successfully.")
        print("DEBUG: Importing models")
        from models import Header, Banner, About, WhyChoose, Highlight, Service, Event, TeamMember, Contact, Footer
        print("Models imported successfully.")
    except Exception as e:
        print(f"Error initializing SQLAlchemy or Flask-Migrate: {str(e)}")
        db_config_ok = False
        db = None
        migrate = None
else:
    print("Database initialization skipped due to missing config.")


# --- Vercel Build Step: Run Migrations ---
if os.getenv('RUN_VERCEL_MIGRATIONS') == '1' and db_config_ok and db and migrate:
    print("Running database migrations during Vercel build...")
    with app.app_context():
        try:
            migrate_upgrade()
            print("Database migration completed successfully.")
        except Exception as e:
            print(f"Database migration failed: {e}")

# --- App Context Setup ---
with app.app_context():
    if db:
        try:
            print("App context entered successfully for potential setup.")
        except Exception as e:
            print(f"Error during app context setup: {str(e)}")

# --- Helpers ---
COOKIE_NAME = 'token'
LOGIN_ENDPOINT = 'login'
ALLOW_NO_DB = os.getenv("ALLOW_NO_DB", "0") == "1"

def _static_ctx():
    """Return a safe, attribute-friendly context for templates (no DB)."""
    return dict(
        header=NS(logo=""),
        banner=NS(title="", subtitle="", image=""),
        about=NS(description="", logo="", collaborators=0, students=0, projects=0, clicks=0),
        why_choose=[],
        highlights=[],
        services=[],
        additional_services="",
        events=[],
        team=[],
        contact=NS(location="", email="", phone=""),
        footer=NS(address="", email="", phone="", linkedin="", github="", twitter="")
    )

def handle_unauthorized(is_api, error_message, redirect_to=LOGIN_ENDPOINT):
    """Helper to handle unauthorized responses consistently."""
    print(f"Unauthorized access: {error_message}")
    response = make_response(
        jsonify({"error": error_message}) if is_api else redirect(url_for(redirect_to))
    )
    response.set_cookie(COOKIE_NAME, '', expires=0, httponly=True, secure=True, samesite='Lax')
    return response, (401 if is_api else 302)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check Firebase Auth initialization
        if not firebase_admin_initialized or auth is None:
            # Fix: don't return (tuple, 500)
            resp, _ = handle_unauthorized(
                request.path.startswith('/api/'),
                "Authentication service is not configured on the server."
            )
            return resp, 500

        # Extract session cookie
        id_token = request.cookies.get(COOKIE_NAME)
        if not id_token:
            return handle_unauthorized(
                request.path.startswith('/api/'),
                "Unauthorized: No session cookie found."
            )

        try:
            # Verify session cookie
            decoded_token = auth.verify_session_cookie(id_token, check_revoked=True)
            request.user = decoded_token  # Attach user info
            return f(*args, **kwargs)
        except (fb_auth.InvalidSessionCookieError, fb_auth.RevokedSessionCookieError, fb_auth.FirebaseError):
            print("Session cookie verification failed.")
            return handle_unauthorized(
                request.path.startswith('/api/'),
                "Unauthorized: Invalid or expired session. Please log in again."
            )
        except Exception as e:
            print(f"Critical error during authentication: {str(e)}")
            return handle_unauthorized(
                request.path.startswith('/api/'),
                "Unauthorized: An unexpected error occurred."
            )
    return decorated_function

# --- Authentication Routes ---
@app.route('/login', methods=['GET'])
def login():
    if firebase_admin_initialized and auth:
        id_token = request.cookies.get('token')
        if id_token:
            try:
                auth.verify_session_cookie(id_token, check_revoked=False)
                return redirect(url_for('cms'))
            except Exception as e:
                print(f"Attempted redirect to CMS for existing cookie failed verification: {e}")

    if not firebase_admin_initialized or auth is None:
        return "Authentication service is not configured on the server. Cannot access login.", 500

    return render_template('login.html')

@app.route('/sessionLogin', methods=['POST'])
def session_login():
    if not firebase_admin_initialized or auth is None:
        return jsonify({'error': 'Authentication service is not configured on the server'}), 500

    id_token = (request.json or {}).get('idToken')
    if not id_token:
        print("No ID token provided in /sessionLogin request")
        return jsonify({'error': 'No ID token provided'}), 401

    try:
        expires_in = 60 * 60 * 24 * 5  # 5 days
        session_cookie = auth.create_session_cookie(id_token, expires_in=expires_in)
        print("Firebase session cookie created successfully.")

        response = make_response(jsonify({'status': 'success'}))
        response.set_cookie('token', session_cookie, max_age=expires_in, httponly=True, secure=True, samesite='Lax')
        return response, 200
    except Exception as e:
        print(f"Error creating Firebase session cookie: {str(e)}")
        return jsonify({'error': str(e)}), 401

@app.route('/logout', methods=['POST'])
def logout():
    print("Logging out user - clearing cookie.")
    response = make_response(jsonify({'status': 'success'}))
    response.set_cookie('token', '', expires=0, httponly=True, secure=True, samesite='Lax')
    return response, 200

# --- Website Routes ---
@app.route('/')
def index():
    # Hard switch: render the site without any DB calls
    if ALLOW_NO_DB:
        return render_template('index.html', **_static_ctx())

    # If DB not configured at all, show maintenance (or static fallback if you prefer)
    if db is None:
        return render_template('maintenance.html'), 503

    try:
        # DB-backed render
        header = Header.query.first()
        banner = Banner.query.first()
        about = About.query.first()

        why_choose = WhyChoose.query.order_by(WhyChoose.order_id).all() if hasattr(WhyChoose, 'order_id') else WhyChoose.query.all()
        highlights = Highlight.query.order_by(Highlight.order_id).all() if hasattr(Highlight, 'order_id') else Highlight.query.all()

        services_q = Service.query.filter_by(is_additional=False)
        services = services_q.order_by(Service.order_id).all() if hasattr(Service, 'order_id') else services_q.all()

        additional_services_entry = Service.query.filter_by(is_additional=True).first()
        additional_services_text = additional_services_entry.additional_services if additional_services_entry else ''

        events = Event.query.order_by(Event.order_id).all() if hasattr(Event, 'order_id') else Event.query.all()
        team = TeamMember.query.order_by(TeamMember.order_id).all() if hasattr(TeamMember, 'order_id') else TeamMember.query.all()
        contact = Contact.query.first()
        footer = Footer.query.first()

        return render_template('index.html',
                               header=header, banner=banner, about=about,
                               why_choose=why_choose, highlights=highlights,
                               services=services, additional_services=additional_services_text,
                               events=events, team=team, contact=contact, footer=footer)

    except (OperationalError, SQLAlchemyError, Exception) as e:
        # DB exploded (quota, SSL, etc.) — serve static site instead of 500
        app.logger.error("DB failure on / : %s", e)
        return render_template('index.html', **_static_ctx())

# --- CMS Route ---
@app.route('/cms')
@login_required
def cms():
    if db is None:
        return "Database is not configured. CMS is inaccessible.", 500
    return render_template('cms.html')

# --- API Endpoints for CMS ---
@app.route('/api/header', methods=['GET'])
@login_required
def get_header():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    header = Header.query.first()
    return jsonify({"logo": header.logo if header else ""})

@app.route('/api/banner', methods=['GET'])
@login_required
def get_banner():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    banner = Banner.query.first()
    return jsonify({
        "title": banner.title if banner else "",
        "subtitle": banner.subtitle if banner else "",
        "image": banner.image if banner else ""
    })

@app.route('/api/about', methods=['GET'])
@login_required
def get_about():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    about = About.query.first()
    return jsonify({
        "description": about.description if about else "",
        "logo": about.logo if about else "",
        "collaborators": about.collaborators if about else 0,
        "students": about.students if about else 0,
        "projects": about.projects if about else 0,
        "clicks": about.clicks if about else 0
    })

@app.route('/api/why_choose', methods=['GET'])
@login_required
def get_why_choose():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    why_choose = WhyChoose.query.order_by(WhyChoose.order_id).all() if hasattr(WhyChoose, 'order_id') else WhyChoose.query.all()
    return jsonify([
        {"id": wc.id, "title": wc.title, "icon": wc.icon, "description": wc.description, "order_id": getattr(wc, 'order_id', None)}
        for wc in why_choose
    ])

@app.route('/api/highlight', methods=['GET'])
@login_required
def get_highlights():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    highlights = Highlight.query.order_by(Highlight.order_id).all() if hasattr(Highlight, 'order_id') else Highlight.query.all()
    return jsonify([
        {"id": h.id, "image": h.image, "order_id": getattr(h, 'order_id', None)}
        for h in highlights
    ])

@app.route('/api/service', methods=['GET'])
@login_required
def get_services():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    services_query = Service.query.filter_by(is_additional=False)
    services = services_query.order_by(Service.order_id).all() if hasattr(Service, 'order_id') else services_query.all()
    return jsonify([
        {"id": s.id, "title": s.title, "icon": s.icon, "description": s.description, "order_id": getattr(s, 'order_id', None)}
        for s in services
    ])

@app.route('/api/additional_services', methods=['GET'])
@login_required
def get_additional_services():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    additional = Service.query.filter_by(is_additional=True).first()
    if additional:
        return jsonify({"additional_services": additional.additional_services or ""})
    else:
        try:
            additional = Service(title="Additional Services", icon=None, description=None, additional_services="", is_additional=True)
            if hasattr(Service, 'order_id'):
                additional.order_id = 0
            db.session.add(additional)
            db.session.commit()
            print("Created default Additional Services entry.")
            return jsonify({"additional_services": ""})
        except Exception as e:
            print(f"Error creating default Additional Services entry: {e}")
            db.session.rollback()
            return jsonify({"additional_services": ""})

@app.route('/api/event', methods=['GET'])
@login_required
def get_events():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    events = Event.query.order_by(Event.order_id).all() if hasattr(Event, 'order_id') else Event.query.all()
    return jsonify([
        {"id": e.id, "title": e.title, "year": e.year, "image": e.image, "order_id": getattr(e, 'order_id', None)}
        for e in events
    ])

@app.route('/api/team', methods=['GET'])
@login_required
def get_team():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    team = TeamMember.query.order_by(TeamMember.order_id).all() if hasattr(TeamMember, 'order_id') else TeamMember.query.all()
    return jsonify([
        {"id": t.id, "name": t.name, "title": t.title, "bio": t.bio,
         "image": t.image, "linkedin": t.linkedin, "github": t.github, "order_id": getattr(t, 'order_id', None)}
        for t in team
    ])

@app.route('/api/contact', methods=['GET'])
@login_required
def get_contact():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    contact = Contact.query.first()
    return jsonify({
        "location": contact.location if contact else "",
        "email": contact.email if contact else "",
        "phone": contact.phone if contact else ""
    })

@app.route('/api/footer', methods=['GET'])
@login_required
def get_footer():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    footer = Footer.query.first()
    return jsonify({
        "address": footer.address if footer else "",
        "email": footer.email if footer else "",
        "phone": footer.phone if footer else "",
        "linkedin": footer.linkedin if footer else "",
        "github": footer.github if footer else "",
        "twitter": footer.twitter if footer else ""
    })

# --- POST/PUT/DELETE Endpoints for CMS ---
@app.route('/api/header', methods=['POST'])
@login_required
def update_header():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    header = Header.query.first()
    if not header:
        header = Header(logo=data.get('logo', ''))
        db.session.add(header)
    else:
        header.logo = data.get('logo', header.logo)
    db.session.commit()
    return jsonify({"message": "Header updated successfully!"})

@app.route('/api/banner', methods=['POST'])
@login_required
def update_banner():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    banner = Banner.query.first()
    if not banner:
        banner = Banner(
            title=data.get('title', ''),
            subtitle=data.get('subtitle', ''),
            image=data.get('image', '')
        )
        db.session.add(banner)
    else:
        banner.title = data.get('title', banner.title)
        banner.subtitle = data.get('subtitle', banner.subtitle)
        banner.image = data.get('image', banner.image)
    db.session.commit()
    return jsonify({"message": "Banner updated successfully!"})

@app.route('/api/about', methods=['POST'])
@login_required
def update_about():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    about = About.query.first()
    if not about:
        about = About(
            description=data.get('description', ''),
            logo=data.get('logo', ''),
            collaborators=data.get('collaborators', 0),
            students=data.get('students', 0),
            projects=data.get('projects', 0),
            clicks=data.get('clicks', 0)
        )
        db.session.add(about)
    else:
        about.description = data.get('description', about.description)
        about.logo = data.get('logo', about.logo)
        about.collaborators = data.get('collaborators', about.collaborators)
        about.students = data.get('students', about.students)
        about.projects = data.get('projects', about.projects)
        about.clicks = data.get('clicks', about.clicks)
    db.session.commit()
    return jsonify({"message": "About Us updated successfully!"})

@app.route('/api/why_choose', methods=['POST'])
@login_required
def add_why_choose():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    if hasattr(WhyChoose, 'order_id'):
        max_order = db.session.query(func.max(WhyChoose.order_id)).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0

    why_choose = WhyChoose(
        title=data.get('title', ''),
        icon=data.get('icon', ''),
        description=data.get('description', ''),
    )
    if hasattr(WhyChoose, 'order_id'):
        why_choose.order_id = new_order_id

    db.session.add(why_choose)
    db.session.commit()
    response_data = {"message": "Why Choose card added successfully!", "id": why_choose.id}
    if hasattr(why_choose, 'order_id'):
        response_data["order_id"] = why_choose.order_id
    return jsonify(response_data), 201

@app.route('/api/why_choose/<int:id>', methods=['PUT'])
@login_required
def update_why_choose(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    why_choose = WhyChoose.query.get(id)
    if why_choose:
        why_choose.title = data.get('title', why_choose.title)
        why_choose.icon = data.get('icon', why_choose.icon)
        why_choose.description = data.get('description', why_choose.description)
        db.session.commit()
        return jsonify({"message": "Why Choose card updated successfully!"})
    return jsonify({"message": "Card not found!"}), 404

@app.route('/api/why_choose/<int:id>', methods=['DELETE'])
@login_required
def delete_why_choose(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    why_choose = WhyChoose.query.get(id)
    if why_choose:
        deleted_order_id = getattr(why_choose, 'order_id', None)
        db.session.delete(why_choose)
        db.session.commit()
        if deleted_order_id is not None and hasattr(WhyChoose, 'order_id'):
            items_to_reorder = WhyChoose.query.filter(WhyChoose.order_id > deleted_order_id).order_by(WhyChoose.order_id).all()
            for item in items_to_reorder:
                item.order_id -= 1
            db.session.commit()
        return jsonify({"message": "Why Choose card deleted successfully!"})
    return jsonify({"message": "Card not found!"}), 404

@app.route('/api/why_choose/<int:id>/move', methods=['POST'])
@login_required
def move_why_choose(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    if not hasattr(WhyChoose, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Why Choose."}), 400

    direction = (request.json or {}).get('direction')
    item_to_move = WhyChoose.query.get(id)
    if not item_to_move:
        return jsonify({"message": "Card not found!"}), 404

    all_items = WhyChoose.query.order_by(WhyChoose.order_id).all()
    ids = [i.id for i in all_items]
    try:
        current_index = ids.index(id)
    except ValueError:
        return jsonify({"message": "Card not found in ordered list!"}), 404

    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
    for index, item in enumerate(all_items):
        item.order_id = index + 1
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Why Choose card moved successfully.'})

@app.route('/api/highlight', methods=['POST'])
@login_required
def add_highlight():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    if hasattr(Highlight, 'order_id'):
        max_order = db.session.query(func.max(Highlight.order_id)).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0

    highlight = Highlight(image=data.get('image', ''))
    if hasattr(Highlight, 'order_id'):
        highlight.order_id = new_order_id

    db.session.add(highlight)
    db.session.commit()
    response_data = {"message": "Highlight added successfully!", "id": highlight.id}
    if hasattr(highlight, 'order_id'):
        response_data["order_id"] = highlight.order_id
    return jsonify(response_data), 201

@app.route('/api/highlight/<int:id>', methods=['PUT'])
@login_required
def update_highlight(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    highlight = Highlight.query.get(id)
    if highlight:
        highlight.image = data.get('image', highlight.image)
        db.session.commit()
        return jsonify({"message": "Highlight updated successfully!"})
    return jsonify({"message": "Highlight not found!"}), 404

@app.route('/api/highlight/<int:id>', methods=['DELETE'])
@login_required
def delete_highlight(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    highlight = Highlight.query.get(id)
    if highlight:
        deleted_order_id = getattr(highlight, 'order_id', None)
        db.session.delete(highlight)
        db.session.commit()
        if deleted_order_id is not None and hasattr(Highlight, 'order_id'):
            items_to_reorder = Highlight.query.filter(Highlight.order_id > deleted_order_id).order_by(Highlight.order_id).all()
            for item in items_to_reorder:
                item.order_id -= 1
            db.session.commit()
        return jsonify({"message": "Highlight deleted successfully!"})
    return jsonify({"message": "Highlight not found!"}), 404

@app.route('/api/highlight/<int:id>/move', methods=['POST'])
@login_required
def move_highlight(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    if not hasattr(Highlight, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Highlights."}), 400

    direction = (request.json or {}).get('direction')
    item_to_move = Highlight.query.get(id)
    if not item_to_move:
        return jsonify({"message": "Highlight not found!"}), 404

    all_items = Highlight.query.order_by(Highlight.order_id).all()
    ids = [i.id for i in all_items]
    try:
        current_index = ids.index(id)
    except ValueError:
        return jsonify({"message": "Highlight not found in ordered list!"}), 404

    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
    for index, item in enumerate(all_items):
        item.order_id = index + 1
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Highlight moved successfully.'})

@app.route('/api/service', methods=['POST'])
@login_required
def add_service():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    if data.get('is_additional', False):
        return jsonify({"message": "Use the additional services endpoint for that."}), 400

    if hasattr(Service, 'order_id'):
        max_order = db.session.query(func.max(Service.order_id)).filter_by(is_additional=False).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0

    service = Service(
        title=data.get('title', ''),
        icon=data.get('icon', ''),
        description=data.get('description', ''),
        is_additional=False,
    )
    if hasattr(Service, 'order_id'):
        service.order_id = new_order_id

    db.session.add(service)
    db.session.commit()
    response_data = {"message": "Service added successfully!", "id": service.id}
    if hasattr(service, 'order_id'):
        response_data["order_id"] = service.order_id
    return jsonify(response_data), 201

@app.route('/api/service/<int:id>', methods=['PUT'])
@login_required
def update_service(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    service = Service.query.get(id)
    if service and not service.is_additional:
        service.title = data.get('title', service.title)
        service.icon = data.get('icon', service.icon)
        service.description = data.get('description', service.description)
        db.session.commit()
        return jsonify({"message": "Service updated successfully!"})
    return jsonify({"message": "Service not found or is the additional services entry!"}), 404

@app.route('/api/service/<int:id>', methods=['DELETE'])
@login_required
def delete_service(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    service = Service.query.get(id)
    if service and not service.is_additional:
        deleted_order_id = getattr(service, 'order_id', None)
        db.session.delete(service)
        db.session.commit()
        if deleted_order_id is not None and hasattr(Service, 'order_id'):
            items_to_reorder = Service.query.filter_by(is_additional=False).filter(Service.order_id > deleted_order_id).order_by(Service.order_id).all()
            for item in items_to_reorder:
                item.order_id -= 1
            db.session.commit()
        return jsonify({"message": "Service deleted successfully!"})
    return jsonify({"message": "Service not found or is the additional services entry!"}), 404

@app.route('/api/service/<int:id>/move', methods=['POST'])
@login_required
def move_service(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    if not hasattr(Service, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Services."}), 400

    direction = (request.json or {}).get('direction')
    item_to_move = Service.query.get(id)
    if not item_to_move or item_to_move.is_additional:
        return jsonify({"message": "Service not found or is the additional services entry!"}), 404

    all_items = Service.query.filter_by(is_additional=False).order_by(Service.order_id).all()
    ids = [i.id for i in all_items]
    try:
        current_index = ids.index(id)
    except ValueError:
        return jsonify({"message": "Service not found in ordered list!"}), 404

    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
    for index, item in enumerate(all_items):
        item.order_id = index + 1
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Service moved successfully.'})

@app.route('/api/additional_services', methods=['POST'])
@login_required
def update_additional_services():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    additional = Service.query.filter_by(is_additional=True).first()
    if not additional:
        additional = Service(title="Additional Services", icon=None, description=None, additional_services=data.get('additional_services', ''), is_additional=True)
        if hasattr(Service, 'order_id'):
            additional.order_id = 0
        db.session.add(additional)
    else:
        additional.additional_services = data.get('additional_services', additional.additional_services)
    db.session.commit()
    return jsonify({"message": "Additional Services updated successfully!"})

@app.route('/api/event', methods=['POST'])
@login_required
def add_event():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    if hasattr(Event, 'order_id'):
        max_order = db.session.query(func.max(Event.order_id)).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0

    event = Event(
        title=data.get('title', ''),
        year=data.get('year', ''),
        image=data.get('image', '')
    )
    if hasattr(Event, 'order_id'):
        event.order_id = new_order_id

    db.session.add(event)
    db.session.commit()
    response_data = {"message": "Event added successfully!", "id": event.id}
    if hasattr(event, 'order_id'):
        response_data["order_id"] = event.order_id
    return jsonify(response_data), 201

@app.route('/api/event/<int:id>', methods=['PUT'])
@login_required
def update_event(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    event = Event.query.get(id)
    if event:
        event.title = data.get('title', event.title)
        event.year = data.get('year', event.year)
        event.image = data.get('image', event.image)
        db.session.commit()
        return jsonify({"message": "Event updated successfully!"})
    return jsonify({"message": "Event not found!"}), 404

@app.route('/api/event/<int:id>', methods=['DELETE'])
@login_required
def delete_event(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    event = Event.query.get(id)
    if event:
        deleted_order_id = getattr(event, 'order_id', None)
        db.session.delete(event)
        db.session.commit()
        if deleted_order_id is not None and hasattr(Event, 'order_id'):
            items_to_reorder = Event.query.filter(Event.order_id > deleted_order_id).order_by(Event.order_id).all()
            for item in items_to_reorder:
                item.order_id -= 1
            db.session.commit()
        return jsonify({"message": "Event deleted successfully!"})
    return jsonify({"message": "Event not found!"}), 404

@app.route('/api/event/<int:id>/move', methods=['POST'])
@login_required
def move_event(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    if not hasattr(Event, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Events."}), 400

    direction = (request.json or {}).get('direction')
    item_to_move = Event.query.get(id)
    if not item_to_move:
        return jsonify({"message": "Event not found!"}), 404

    all_items = Event.query.order_by(Event.order_id).all()
    ids = [i.id for i in all_items]
    try:
        current_index = ids.index(id)
    except ValueError:
        return jsonify({"message": "Event not found in ordered list!"}), 404

    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
    for index, item in enumerate(all_items):
        item.order_id = index + 1
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Event moved successfully.'})

@app.route('/api/team', methods=['POST'])
@login_required
def add_team_member():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    if hasattr(TeamMember, 'order_id'):
        max_order = db.session.query(func.max(TeamMember.order_id)).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0

    try:
        team_member = TeamMember(
            name=data.get('name', ''),
            title=data.get('title', ''),
            bio=data.get('bio', ''),
            image=data.get('image', ''),
            linkedin=data.get('linkedin', None),
            github=data.get('github', None)
        )
        if hasattr(TeamMember, 'order_id'):
            team_member.order_id = new_order_id

        db.session.add(team_member)
        db.session.commit()
        response_data = {"message": "Team member added successfully!", "id": team_member.id}
        if hasattr(team_member, 'order_id'):
            response_data["order_id"] = team_member.order_id
        return jsonify(response_data), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error in add_team_member: {str(e)}")
        return jsonify({"error": f"Failed to add team member: {str(e)}"}), 500

@app.route('/api/team/<int:id>', methods=['PUT'])
@login_required
def update_team_member(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    team_member = TeamMember.query.get(id)
    if team_member:
        try:
            team_member.name = data.get('name', team_member.name)
            team_member.title = data.get('title', team_member.title)
            team_member.bio = data.get('bio', team_member.bio)
            team_member.image = data.get('image', team_member.image)
            team_member.linkedin = data.get('linkedin', team_member.linkedin)
            team_member.github = data.get('github', team_member.github)
            db.session.commit()
            return jsonify({"message": "Team member updated successfully!"})
        except Exception as e:
            db.session.rollback()
            print(f"Error in update_team_member for ID {id}: {str(e)}")
            return jsonify({"error": f"Failed to update team member: {str(e)}"}), 500
    return jsonify({"message": "Team member not found!"}), 404

@app.route('/api/team/<int:id>', methods=['DELETE'])
@login_required
def delete_team_member(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    team_member = TeamMember.query.get(id)
    if team_member:
        deleted_order_id = getattr(team_member, 'order_id', None)
        db.session.delete(team_member)
        db.session.commit()
        if deleted_order_id is not None and hasattr(TeamMember, 'order_id'):
            items_to_reorder = TeamMember.query.filter(TeamMember.order_id > deleted_order_id).order_by(TeamMember.order_id).all()
            for item in items_to_reorder:
                item.order_id -= 1
            db.session.commit()
        return jsonify({"message": "Team member deleted successfully!"})
    return jsonify({"message": "Team member not found!"}), 404

@app.route('/api/team/<int:id>/move', methods=['POST'])
@login_required
def move_team_member(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    if not hasattr(TeamMember, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Team Members."}), 400

    direction = (request.json or {}).get('direction')
    item_to_move = TeamMember.query.get(id)
    if not item_to_move:
        return jsonify({"message": "Team member not found!"}), 404

    all_items = TeamMember.query.order_by(TeamMember.order_id).all()
    ids = [i.id for i in all_items]
    try:
        current_index = ids.index(id)
    except ValueError:
        return jsonify({"message": "Team member not found in ordered list!"}), 404

    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
    for index, item in enumerate(all_items):
        item.order_id = index + 1
    db.session.commit()
    return jsonify({'status': 'success', 'message': 'Team member moved successfully.'})

@app.route('/api/contact', methods=['POST'])
@login_required
def update_contact():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    contact = Contact.query.first()
    if not contact:
        contact = Contact(
            location=data.get('location', ''),
            email=data.get('email', ''),
            phone=data.get('phone', '')
        )
        db.session.add(contact)
    else:
        contact.location = data.get('location', contact.location)
        contact.email = data.get('email', contact.email)
        contact.phone = data.get('phone', contact.phone)
    db.session.commit()
    return jsonify({"message": "Contact updated successfully!"})

@app.route('/api/footer', methods=['POST'])
@login_required
def update_footer():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json or {}
    footer = Footer.query.first()
    if not footer:
        footer = Footer(
            address=data.get('address', ''),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            linkedin=data.get('linkedin', None),
            github=data.get('github', None),
            twitter=data.get('twitter', None)
        )
        db.session.add(footer)
    else:
        footer.address = data.get('address', footer.address)
        footer.email = data.get('email', footer.email)
        footer.phone = data.get('phone', footer.phone)
        footer.linkedin = data.get('linkedin', footer.linkedin)
        footer.github = data.get('github', footer.github)
        footer.twitter = data.get('twitter', footer.twitter)
    db.session.commit()
    return jsonify({"message": "Footer updated successfully!"})

# --- Local Development Server ---
if __name__ == '__main__':
    print("Running Flask app locally...")
    app.run(debug=True)
