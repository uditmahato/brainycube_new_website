# --- Imports ---
from flask import Flask, render_template, request, jsonify, redirect, url_for, make_response, session
import json
import os
import sys
import base64
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import auth, credentials
from functools import wraps
from flask_migrate import Migrate, upgrade as migrate_upgrade
from sqlalchemy import func

# Load environment variables first
load_dotenv()
print("DEBUG: Loaded .env file")

# --- App Initialization ---
app = Flask(__name__)

# Secret key
app.secret_key = os.getenv('FLASK_SECRET_KEY') or 'super-fallback-secret-key-not-for-production-ever'
if not os.getenv('FLASK_SECRET_KEY'):
    print("Warning: FLASK_SECRET_KEY not set. Using default for development.")

# --- Firebase Initialization ---
firebase_admin_initialized = False
auth = None
try:
    firebase_credentials_base64 = os.getenv('FIREBASE_CREDENTIALS_BASE64')
    if firebase_credentials_base64:
        credentials_json_str = base64.b64decode(firebase_credentials_base64).decode('utf-8')
        cred_info = json.loads(credentials_json_str)
        cred = credentials.Certificate(cred_info)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            print("Firebase Admin SDK initialized successfully...")
        else:
            print("Firebase Admin SDK already initialized.")
        auth = firebase_admin.auth
        firebase_admin_initialized = True
    else:
        print("FIREBASE_CREDENTIALS_BASE64 environment variable not set...")
except Exception as e:
    print(f"Error initializing Firebase Admin SDK: {str(e)}")
    firebase_admin_initialized = False
    auth = None

# --- Database Configuration ---
database_uri = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
db_config_ok = False
db = None
migrate = None

if database_uri:
    if database_uri.startswith('postgres://'):
        database_uri = database_uri.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db_config_ok = True
    print("Database URI loaded from environment variable:", database_uri)
else:
    print("Warning: DATABASE_URL or POSTGRES_URL not set. Database connection not configured.")

# Initialize SQLAlchemy and Flask-Migrate
if db_config_ok:
    try:
        print("DEBUG: Importing db from extensions")
        from extensions import db
        print("DEBUG: db object from extensions =", db)
        if db is None:
            raise ValueError("db is None after import from extensions")
        db.init_app(app)
        print("SQLAlchemy initialized successfully.")
        migrate = Migrate(app, db)
        print("Flask-Migrate initialized successfully.")
        # Import models after db initialization
        print("DEBUG: Importing models")
        from models import Header, Banner, About, WhyChoose, Highlight, Service, Event, TeamMember, Contact, Footer
        print("Models imported successfully.")
    except Exception as e:
        print(f"Error initializing SQLAlchemy or Flask-Migrate: {str(e)}")
        db_config_ok = False
        db = None
        migrate = None
else:
    print("Database initialization skipped due to missing URI.")

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
# --- Middleware to protect routes ---
# Configuration
COOKIE_NAME = 'token'
LOGIN_ENDPOINT = 'login'
firebase_admin_initialized = True  # Assume initialized for brevity

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
            return handle_unauthorized(
                request.path.startswith('/api/'),
                "Authentication service is not configured on the server."
            ), 500

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

            # Optional: Add RBAC check
            # if 'admin' not in decoded_token.get('claims', {}):
            #     return handle_unauthorized(
            #         request.path.startswith('/api/'),
            #         "Unauthorized: Admin access required."
            #     )

            return f(*args, **kwargs)  # Proceed to route handler

        except (auth.InvalidSessionCookieError, auth.RevokedSessionCookieError, auth.FirebaseError) as e:
            print(f"Session cookie verification failed: {type(e).__name__}")
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

# Login page route
@app.route('/login', methods=['GET'])
def login():
    # Redirect to CMS if already logged in and Firebase is configured
    # This prevents showing the login page if they have a valid session cookie
    if firebase_admin_initialized and auth:
        id_token = request.cookies.get('token')
        if id_token:
            try:
                # Quickly verify cookie to see if it's valid
                auth.verify_session_cookie(id_token, check_revoked=False) # No need for full revoke check on every page load
                return redirect(url_for('cms')) # Redirect if valid
            except Exception as e:
                 print(f"Attempted redirect to CMS for existing cookie failed verification: {e}")
                 # Cookie is invalid, continue to render login page

    if not firebase_admin_initialized or auth is None:
         return "Authentication service is not configured on the server. Cannot access login.", 500

    return render_template('login.html')

# Route to set session cookie after Firebase Authentication (POST from client-side login)
@app.route('/sessionLogin', methods=['POST'])
def session_login():
    if not firebase_admin_initialized or auth is None:
         return jsonify({'error': 'Authentication service is not configured on the server'}), 500

    id_token = request.json.get('idToken')
    if not id_token:
        print("No ID token provided in /sessionLogin request")
        return jsonify({'error': 'No ID token provided'}), 401

    try:
        # Set session expiration to 5 days (max 2 weeks allowed by Firebase)
        expires_in = 60 * 60 * 24 * 5
        # Create the Firebase session cookie from the ID token
        session_cookie = auth.create_session_cookie(id_token, expires_in=expires_in)
        print("Firebase session cookie created successfully.")

        response = make_response(jsonify({'status': 'success'}))
        # Set the cookie on the response
        # httponly=True: Prevents client-side JavaScript from accessing the cookie
        # secure=True: Ensures the cookie is only sent over HTTPS (Vercel uses HTTPS)
        # samesite='Lax': Helps prevent CSRF attacks
        response.set_cookie('token', session_cookie, max_age=expires_in, httponly=True, secure=True, samesite='Lax')
        return response, 200 # Return 200 on success
    except Exception as e:
        print(f"Error creating Firebase session cookie: {str(e)}")
        return jsonify({'error': str(e)}), 401

# Logout route (POST from client-side logout button)
@app.route('/logout', methods=['POST'])
def logout():
    # Client-side Firebase logout should also be performed by the frontend.
    # Server-side invalidation if using explicit revocation lists would go here.
    # For now, simply clear the session cookie.
    print("Logging out user - clearing cookie.")
    response = make_response(jsonify({'status': 'success'}))
    # Clear the cookie by setting its expiration to the past
    response.set_cookie('token', '', expires=0, httponly=True, secure=True, samesite='Lax') # Clear securely
    return response, 200


# --- Website Routes ---

@app.route('/')
def index():
    # Check if database is configured before attempting to query
    if db is None:
        # Render a maintenance page or error if DB is down/not configured
        return "Database is not configured. Site content unavailable.", 500 # Consider rendering an HTML error page

    # Fetch data for the public website view
    # Fetch by querying the database models
    header = Header.query.first()
    banner = Banner.query.first()
    about = About.query.first()

    # Fetch list items, ordering by 'order_id'.
    # Use hasattr check for robustness in case models lack order_id for some reason
    why_choose = WhyChoose.query.order_by(WhyChoose.order_id).all() if hasattr(WhyChoose, 'order_id') else WhyChoose.query.all()
    highlights = Highlight.query.order_by(Highlight.order_id).all() if hasattr(Highlight, 'order_id') else Highlight.query.all()
    # Filter out the special 'additional services' entry from the main services list
    services = Service.query.filter_by(is_additional=False).order_by(Service.order_id).all() if hasattr(Service, 'order_id') else Service.query.filter_by(is_additional=False).all()
    # Fetch the single 'additional services' entry
    additional_services_entry = Service.query.filter_by(is_additional=True).first()
    additional_services_text = additional_services_entry.additional_services if additional_services_entry else '' # Get the text or empty string

    events = Event.query.order_by(Event.order_id).all() if hasattr(Event, 'order_id') else Event.query.all()
    team = TeamMember.query.order_by(TeamMember.order_id).all() if hasattr(TeamMember, 'order_id') else TeamMember.query.all()
    contact = Contact.query.first()
    footer = Footer.query.first()

    # Render the main index template, passing the fetched data
    return render_template('index.html',
                          header=header, banner=banner, about=about,
                          why_choose=why_choose, highlights=highlights,
                          services=services, additional_services=additional_services_text,
                          events=events, team=team, contact=contact, footer=footer)

# --- CMS Route ---
@app.route('/cms')
@login_required # Protect the CMS route
def cms():
    # Check if database is configured, as CMS depends heavily on it
    if db is None:
        return "Database is not configured. CMS is inaccessible.", 500 # Or render error page

    # The CMS template (cms.html) will load and then make API calls
    # to fetch the data dynamically using JavaScript.
    return render_template('cms.html')


# --- API Endpoints for CMS ---
# All API endpoints that interact with the database should check if 'db' is None
# at the beginning.

# GET Endpoints to fetch existing data

@app.route('/api/header', methods=['GET'])
@login_required
def get_header():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    header = Header.query.first()
    # Return data as a dictionary. If no header, return empty strings/defaults.
    return jsonify({"logo": header.logo if header else ""})

@app.route('/api/banner', methods=['GET'])
@login_required
def get_banner():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    banner = Banner.query.first()
    # Return data as a dictionary. If no banner, return empty strings/defaults.
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
    # Return data as a dictionary. If no about, return empty strings/defaults.
    return jsonify({
        "description": about.description if about else "",
        "logo": about.logo if about else "",
        "collaborators": about.collaborators if about else 0,
        "students": about.students if about else 0,
        "projects": about.projects if about else 0,
        "clicks": about.clicks if about else 0
    })

# GET for WhyChoose - fetches all, ordered
@app.route('/api/why_choose', methods=['GET'])
@login_required
def get_why_choose():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    # Fetch WhyChoose ordered by order_id
    # Assume order_id exists due to migrations, but keep hasattr for robustness
    why_choose = WhyChoose.query.order_by(WhyChoose.order_id).all() if hasattr(WhyChoose, 'order_id') else WhyChoose.query.all()
    # Serialize the list of objects to JSON
    return jsonify([
        {"id": wc.id, "title": wc.title, "icon": wc.icon, "description": wc.description, "order_id": wc.order_id if hasattr(wc, 'order_id') else None}
        for wc in why_choose
    ])

# GET for Highlights - fetches all, ordered
@app.route('/api/highlight', methods=['GET'])
@login_required
def get_highlights():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    # Fetch Highlights ordered by order_id (assuming Highlight also has order_id)
    highlights = Highlight.query.order_by(Highlight.order_id).all() if hasattr(Highlight, 'order_id') else Highlight.query.all()
    return jsonify([
        {"id": h.id, "image": h.image, "order_id": h.order_id if hasattr(h, 'order_id') else None}
        for h in highlights
    ])

# GET for Services - fetches all, ordered, excluding additional
@app.route('/api/service', methods=['GET'])
@login_required
def get_services():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    # Fetch Services filtered by is_additional=False, ordered by order_id
    services_query = Service.query.filter_by(is_additional=False)
    services = services_query.order_by(Service.order_id).all() if hasattr(Service, 'order_id') else services_query.all()
    return jsonify([
        {"id": s.id, "title": s.title, "icon": s.icon, "description": s.description, "order_id": s.order_id if hasattr(s, 'order_id') else None}
        for s in services
    ])

# GET for Additional Services - fetches the single entry
@app.route('/api/additional_services', methods=['GET'])
@login_required
def get_additional_services():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    # Find the single entry for additional services
    additional = Service.query.filter_by(is_additional=True).first()
    # Return the text or empty string. If no entry, create a default one.
    if additional:
        return jsonify({"additional_services": additional.additional_services or ""})
    else:
        # Create the default entry if it doesn't exist for easier frontend handling
        try:
            additional = Service(title="Additional Services", icon=None, description=None, additional_services="", is_additional=True)
            # Assign an order_id if the model has it, perhaps a fixed low number like 0
            if hasattr(Service, 'order_id'):
                 additional.order_id = 0 # This item is often displayed separately anyway
            db.session.add(additional)
            db.session.commit()
            print("Created default Additional Services entry.")
            return jsonify({"additional_services": ""}) # Return empty string after creating
        except Exception as e:
            print(f"Error creating default Additional Services entry: {e}")
            db.session.rollback() # Rollback if creation fails
            return jsonify({"additional_services": ""}) # Still return empty on error


# GET for Events - fetches all, ordered
@app.route('/api/event', methods=['GET'])
@login_required
def get_events():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    # Fetch Events ordered by order_id (assuming Event also has order_id)
    events = Event.query.order_by(Event.order_id).all() if hasattr(Event, 'order_id') else Event.query.all()
    return jsonify([
        {"id": e.id, "title": e.title, "year": e.year, "image": e.image, "order_id": e.order_id if hasattr(e, 'order_id') else None}
        for e in events
    ])


# GET for Team - fetches all, ordered
@app.route('/api/team', methods=['GET'])
@login_required
def get_team():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    # Fetch Team Members ordered by order_id (assuming TeamMember also has order_id)
    team = TeamMember.query.order_by(TeamMember.order_id).all() if hasattr(TeamMember, 'order_id') else TeamMember.query.all()
    return jsonify([
        {"id": t.id, "name": t.name, "title": t.title, "bio": t.bio,
         "image": t.image, "linkedin": t.linkedin, "github": t.github, "order_id": t.order_id if hasattr(t, 'order_id') else None}
        for t in team
    ])

@app.route('/api/contact', methods=['GET'])
@login_required
def get_contact():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    contact = Contact.query.first()
    # Return data as a dictionary. If no contact, return empty strings/defaults.
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
    # Return data as a dictionary. If no footer, return empty strings/defaults.
    return jsonify({
        "address": footer.address if footer else "",
        "email": footer.email if footer else "",
        "phone": footer.phone if footer else "",
        "linkedin": footer.linkedin if footer else "",
        "github": footer.github if footer else "",
        "twitter": footer.twitter if footer else ""
    })


# --- POST/PUT/DELETE Endpoints for CMS ---
# Ensure all these also check if db is None at the start

@app.route('/api/header', methods=['POST'])
@login_required
def update_header():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    header = Header.query.first()
    if not header:
        # Create if it doesn't exist
        header = Header(logo=data.get('logo', ''))
        db.session.add(header)
    else:
        # Update existing
        header.logo = data.get('logo', header.logo)
    db.session.commit()
    return jsonify({"message": "Header updated successfully!"})

@app.route('/api/banner', methods=['POST'])
@login_required
def update_banner():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    banner = Banner.query.first()
    if not banner:
        # Create if it doesn't exist
        banner = Banner(
            title=data.get('title', ''),
            subtitle=data.get('subtitle', ''),
            image=data.get('image', '')
        )
        db.session.add(banner)
    else:
        # Update existing
        banner.title = data.get('title', banner.title)
        banner.subtitle = data.get('subtitle', banner.subtitle)
        banner.image = data.get('image', banner.image) # Allow image update
    db.session.commit()
    return jsonify({"message": "Banner updated successfully!"})

@app.route('/api/about', methods=['POST'])
@login_required
def update_about():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    about = About.query.first()
    if not about:
        # Create if it doesn't exist
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
        # Update existing
        about.description = data.get('description', about.description)
        about.logo = data.get('logo', about.logo)
        about.collaborators = data.get('collaborators', about.collaborators)
        about.students = data.get('students', about.students)
        about.projects = data.get('projects', about.projects)
        about.clicks = data.get('clicks', about.clicks)
    db.session.commit()
    return jsonify({"message": "About Us updated successfully!"})

# WhyChoose Add (POST)
@app.route('/api/why_choose', methods=['POST'])
@login_required
def add_why_choose():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    # Ensure order_id exists before using func.max
    if hasattr(WhyChoose, 'order_id'):
        # Get the maximum current order_id and add 1 for the new item
        max_order = db.session.query(func.max(WhyChoose.order_id)).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0 # Or some default if ordering is not enabled

    why_choose = WhyChoose(
        title=data.get('title', ''),
        icon=data.get('icon', ''),
        description=data.get('description', ''),
    )
    # Assign order_id if the model supports it
    if hasattr(WhyChoose, 'order_id'):
         why_choose.order_id = new_order_id

    db.session.add(why_choose)
    db.session.commit()
    # Include order_id in the response if it was assigned
    response_data = {"message": "Why Choose card added successfully!", "id": why_choose.id}
    if hasattr(why_choose, 'order_id'):
        response_data["order_id"] = why_choose.order_id
    return jsonify(response_data), 201 # 201 Created


# WhyChoose Update (PUT)
@app.route('/api/why_choose/<int:id>', methods=['PUT'])
@login_required
def update_why_choose(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    why_choose = WhyChoose.query.get(id)
    if why_choose:
        why_choose.title = data.get('title', why_choose.title)
        why_choose.icon = data.get('icon', why_choose.icon)
        why_choose.description = data.get('description', why_choose.description)
        # Do NOT update order_id via this endpoint; it's handled by the move endpoint
        db.session.commit()
        return jsonify({"message": "Why Choose card updated successfully!"})
    return jsonify({"message": "Card not found!"}), 404


# WhyChoose Delete (DELETE)
@app.route('/api/why_choose/<int:id>', methods=['DELETE'])
@login_required
def delete_why_choose(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    why_choose = WhyChoose.query.get(id)
    if why_choose:
        deleted_order_id = why_choose.order_id if hasattr(why_choose, 'order_id') else None
        db.session.delete(why_choose)
        db.session.commit() # Commit deletion first

        # Reorder remaining items if order_id exists
        if deleted_order_id is not None and hasattr(WhyChoose, 'order_id'):
            # Get all items with order_id > deleted item's order_id, ordered by order_id
            items_to_reorder = WhyChoose.query.filter(WhyChoose.order_id > deleted_order_id).order_by(WhyChoose.order_id).all()
            # Decrement their order_id
            for item in items_to_reorder:
                item.order_id -= 1
            db.session.commit() # Commit reordering

        return jsonify({"message": "Why Choose card deleted successfully!"})
    return jsonify({"message": "Card not found!"}), 404


# WhyChoose Move (POST)
@app.route('/api/why_choose/<int:id>/move', methods=['POST'])
@login_required
def move_why_choose(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    # Check if ordering is configured for this model
    if not hasattr(WhyChoose, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Why Choose."}), 400

    direction = request.json.get('direction')
    item_to_move = WhyChoose.query.get(id)

    if not item_to_move:
        return jsonify({"message": "Card not found!"}), 404

    # Fetch all items in the current order
    all_items = WhyChoose.query.order_by(WhyChoose.order_id).all()
    current_index = -1
    # Find the index of the item to move
    for i, item in enumerate(all_items):
        if item.id == id:
            current_index = i
            break

    if current_index == -1:
         # This case is unlikely if get(id) worked, but included for safety
         return jsonify({"message": "Card not found in ordered list!"}), 404

    target_index = -1
    # Determine the target index based on direction
    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        # If direction is invalid or item is already at the boundary
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    if target_index != -1:
        # Swap the items in the Python list
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]

        # Reassign order_ids based on the new list order
        # Start order_id from 1 for clarity, ensures no gaps or duplicates
        for index, item in enumerate(all_items):
            item.order_id = index + 1

        # Commit the changes to the database
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Why Choose card moved successfully.'})
    else:
        # Should be caught by the check above, but as a fallback
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction.'}), 200


# Highlight Add (POST)
@app.route('/api/highlight', methods=['POST'])
@login_required
def add_highlight():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    # Ensure order_id exists before using func.max
    if hasattr(Highlight, 'order_id'):
         # Get the maximum current order_id and add 1 for the new item
        max_order = db.session.query(func.max(Highlight.order_id)).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0 # Default if ordering is not enabled

    highlight = Highlight(image=data.get('image', ''))
    # Assign order_id if the model supports it
    if hasattr(Highlight, 'order_id'):
         highlight.order_id = new_order_id

    db.session.add(highlight)
    db.session.commit()
     # Include order_id in the response if it was assigned
    response_data = {"message": "Highlight added successfully!", "id": highlight.id}
    if hasattr(highlight, 'order_id'):
        response_data["order_id"] = highlight.order_id
    return jsonify(response_data), 201


# Highlight Update (PUT)
@app.route('/api/highlight/<int:id>', methods=['PUT'])
@login_required
def update_highlight(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    highlight = Highlight.query.get(id)
    if highlight:
        highlight.image = data.get('image', highlight.image)
        db.session.commit()
        return jsonify({"message": "Highlight updated successfully!"})
    return jsonify({"message": "Highlight not found!"}), 404

# Highlight Delete (DELETE)
@app.route('/api/highlight/<int:id>', methods=['DELETE'])
@login_required
def delete_highlight(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    highlight = Highlight.query.get(id)
    if highlight:
        deleted_order_id = highlight.order_id if hasattr(highlight, 'order_id') else None
        db.session.delete(highlight)
        db.session.commit() # Commit deletion first

        # Reorder remaining items if order_id exists
        if deleted_order_id is not None and hasattr(Highlight, 'order_id'):
             items_to_reorder = Highlight.query.filter(Highlight.order_id > deleted_order_id).order_by(Highlight.order_id).all()
             for item in items_to_reorder:
                 item.order_id -= 1
             db.session.commit() # Commit reordering

        return jsonify({"message": "Highlight deleted successfully!"})
    return jsonify({"message": "Highlight not found!"}), 404

# Highlight Move (POST)
@app.route('/api/highlight/<int:id>/move', methods=['POST'])
@login_required
def move_highlight(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    if not hasattr(Highlight, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Highlights."}), 400

    direction = request.json.get('direction')
    item_to_move = Highlight.query.get(id)

    if not item_to_move:
        return jsonify({"message": "Highlight not found!"}), 404

    all_items = Highlight.query.order_by(Highlight.order_id).all()
    current_index = -1
    for i, item in enumerate(all_items):
        if item.id == id:
            current_index = i
            break

    if current_index == -1:
         return jsonify({"message": "Highlight not found in ordered list!"}), 404

    target_index = -1
    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    if target_index != -1:
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
        for index, item in enumerate(all_items):
            item.order_id = index + 1
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Highlight moved successfully.'})
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction.'}), 200


# Service Add (POST)
@app.route('/api/service', methods=['POST'])
@login_required
def add_service():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    # Ensure we only add regular services here via this endpoint
    if data.get('is_additional', False):
        return jsonify({"message": "Use the additional services endpoint for that."}), 400

    # Ensure order_id exists before using func.max
    if hasattr(Service, 'order_id'):
        # Get the maximum current order_id for *non-additional* services
        max_order = db.session.query(func.max(Service.order_id)).filter_by(is_additional=False).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0 # Default if ordering is not enabled

    service = Service(
        title=data.get('title', ''),
        icon=data.get('icon', ''),
        description=data.get('description', ''),
        is_additional=False, # Explicitly False for this endpoint
    )
    # Assign order_id if the model supports it
    if hasattr(Service, 'order_id'):
         service.order_id = new_order_id

    db.session.add(service)
    db.session.commit()
     # Include order_id in the response if it was assigned
    response_data = {"message": "Service added successfully!", "id": service.id}
    if hasattr(service, 'order_id'):
        response_data["order_id"] = service.order_id
    return jsonify(response_data), 201

# Service Update (PUT)
@app.route('/api/service/<int:id>', methods=['PUT'])
@login_required
def update_service(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    service = Service.query.get(id)
    # Ensure the item exists and is NOT the additional services entry
    if service and not service.is_additional:
        service.title = data.get('title', service.title)
        service.icon = data.get('icon', service.icon)
        service.description = data.get('description', service.description)
        # Do NOT update order_id here
        db.session.commit()
        return jsonify({"message": "Service updated successfully!"})
    return jsonify({"message": "Service not found or is the additional services entry!"}), 404


# Service Delete (DELETE)
@app.route('/api/service/<int:id>', methods=['DELETE'])
@login_required
def delete_service(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    service = Service.query.get(id)
    # Ensure the item exists and is NOT the additional services entry
    if service and not service.is_additional:
        deleted_order_id = service.order_id if hasattr(service, 'order_id') else None
        db.session.delete(service)
        db.session.commit() # Commit deletion first

        # Reorder remaining items if order_id exists and it's a list item
        if deleted_order_id is not None and hasattr(Service, 'order_id'):
             # Only reorder non-additional services
             items_to_reorder = Service.query.filter_by(is_additional=False).filter(Service.order_id > deleted_order_id).order_by(Service.order_id).all()
             for item in items_to_reorder:
                 item.order_id -= 1
             db.session.commit() # Commit reordering

        return jsonify({"message": "Service deleted successfully!"})
    return jsonify({"message": "Service not found or is the additional services entry!"}), 404

# Service Move (POST)
@app.route('/api/service/<int:id>/move', methods=['POST'])
@login_required
def move_service(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    if not hasattr(Service, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Services."}), 400

    direction = request.json.get('direction')
    item_to_move = Service.query.get(id)

    # Ensure the item exists and is NOT the additional services entry
    if not item_to_move or item_to_move.is_additional:
        return jsonify({"message": "Service not found or is the additional services entry!"}), 404

    # Fetch only non-additional services for ordering
    all_items = Service.query.filter_by(is_additional=False).order_by(Service.order_id).all()
    current_index = -1
    for i, item in enumerate(all_items):
        if item.id == id:
            current_index = i
            break

    if current_index == -1:
         return jsonify({"message": "Service not found in ordered list!"}), 404

    target_index = -1
    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    if target_index != -1:
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
        for index, item in enumerate(all_items):
            item.order_id = index + 1
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Service moved successfully.'})
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction.'}), 200


# Additional Services Update (POST)
@app.route('/api/additional_services', methods=['POST'])
@login_required
def update_additional_services():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    additional = Service.query.filter_by(is_additional=True).first()
    if not additional:
        # Create it if it doesn't exist
        additional = Service(title="Additional Services", icon=None, description=None, additional_services=data.get('additional_services', ''), is_additional=True)
         # Assign an order_id if the model has it, perhaps a fixed low number like 0, but it won't be part of the ordered list anyway
        if hasattr(Service, 'order_id'):
             additional.order_id = 0 # Assign a fixed low order_id
        db.session.add(additional)
    else:
        # Update existing
        additional.additional_services = data.get('additional_services', additional.additional_services)
    db.session.commit()
    return jsonify({"message": "Additional Services updated successfully!"})


# Event Add (POST)
@app.route('/api/event', methods=['POST'])
@login_required
def add_event():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    # Ensure order_id exists before using func.max
    if hasattr(Event, 'order_id'):
         # Get the maximum current order_id and add 1 for the new item
        max_order = db.session.query(func.max(Event.order_id)).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0 # Default if ordering is not enabled

    event = Event(
        title=data.get('title', ''),
        year=data.get('year', ''),
        image=data.get('image', '')
    )
    # Assign order_id if the model supports it
    if hasattr(Event, 'order_id'):
         event.order_id = new_order_id

    db.session.add(event)
    db.session.commit()
    # Include order_id in the response if it was assigned
    response_data = {"message": "Event added successfully!", "id": event.id}
    if hasattr(event, 'order_id'):
        response_data["order_id"] = event.order_id
    return jsonify(response_data), 201

# Event Update (PUT)
@app.route('/api/event/<int:id>', methods=['PUT'])
@login_required
def update_event(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    event = Event.query.get(id)
    if event:
        event.title = data.get('title', event.title)
        event.year = data.get('year', event.year)
        event.image = data.get('image', event.image)
        db.session.commit()
        return jsonify({"message": "Event updated successfully!"})
    return jsonify({"message": "Event not found!"}), 404

# Event Delete (DELETE)
@app.route('/api/event/<int:id>', methods=['DELETE'])
@login_required
def delete_event(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    event = Event.query.get(id)
    if event:
        deleted_order_id = event.order_id if hasattr(event, 'order_id') else None
        db.session.delete(event)
        db.session.commit() # Commit deletion first

        # Reorder remaining items if order_id exists
        if deleted_order_id is not None and hasattr(Event, 'order_id'):
             items_to_reorder = Event.query.filter(Event.order_id > deleted_order_id).order_by(Event.order_id).all()
             for item in items_to_reorder:
                 item.order_id -= 1
             db.session.commit() # Commit reordering

        return jsonify({"message": "Event deleted successfully!"})
    return jsonify({"message": "Event not found!"}), 404

# Event Move (POST)
@app.route('/api/event/<int:id>/move', methods=['POST'])
@login_required
def move_event(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    if not hasattr(Event, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Events."}), 400

    direction = request.json.get('direction')
    item_to_move = Event.query.get(id)

    if not item_to_move:
        return jsonify({"message": "Event not found!"}), 404

    all_items = Event.query.order_by(Event.order_id).all()
    current_index = -1
    for i, item in enumerate(all_items):
        if item.id == id:
            current_index = i
            break

    if current_index == -1:
         return jsonify({"message": "Event not found in ordered list!"}), 404

    target_index = -1
    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    if target_index != -1:
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
        for index, item in enumerate(all_items):
            item.order_id = index + 1
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Event moved successfully.'})
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction.'}), 200


# TeamMember Add (POST)
@app.route('/api/team', methods=['POST'])
@login_required
def add_team_member():
    if db is None: return jsonify({"error": "Database not configured."}), 500
     # Ensure order_id exists before using func.max
    if hasattr(TeamMember, 'order_id'):
        # Get the maximum current order_id and add 1 for the new item
        max_order = db.session.query(func.max(TeamMember.order_id)).scalar() or 0
        new_order_id = max_order + 1
    else:
        new_order_id = 0 # Default if ordering is not enabled

    team_member = TeamMember(
        name=data.get('name', ''),
        title=data.get('title', ''),
        bio=data.get('bio', ''),
        image=data.get('image', ''),
        linkedin=data.get('linkedin', None), # Use None for nullable fields if key is missing
        github=data.get('github', None)
    )
    # Assign order_id if the model supports it
    if hasattr(TeamMember, 'order_id'):
         team_member.order_id = new_order_id

    db.session.add(team_member)
    db.session.commit()
     # Include order_id in the response if it was assigned
    response_data = {"message": "Team member added successfully!", "id": team_member.id}
    if hasattr(team_member, 'order_id'):
        response_data["order_id"] = team_member.order_id
    return jsonify(response_data), 201

# TeamMember Update (PUT)
@app.route('/api/team/<int:id>', methods=['PUT'])
@login_required
def update_team_member(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    team_member = TeamMember.query.get(id)
    if team_member:
        team_member.name = data.get('name', team_member.name)
        team_member.title = data.get('title', team_member.title)
        team_member.bio = data.get('bio', team_member.bio)
        team_member.image = data.get('image', team_member.image)
        team_member.linkedin = data.get('linkedin', team_member.linkedin) # Use get with existing value as default
        team_member.github = data.get('github', team_member.github)
        # Do NOT update order_id here
        db.session.commit()
        return jsonify({"message": "Team member updated successfully!"})
    return jsonify({"message": "Team member not found!"}), 404

# TeamMember Delete (DELETE)
@app.route('/api/team/<int:id>', methods=['DELETE'])
@login_required
def delete_team_member(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    team_member = TeamMember.query.get(id)
    if team_member:
        deleted_order_id = team_member.order_id if hasattr(team_member, 'order_id') else None
        db.session.delete(team_member)
        db.session.commit() # Commit deletion first

        # Reorder remaining items if order_id exists
        if deleted_order_id is not None and hasattr(TeamMember, 'order_id'):
             items_to_reorder = TeamMember.query.filter(TeamMember.order_id > deleted_order_id).order_by(TeamMember.order_id).all()
             for item in items_to_reorder:
                 item.order_id -= 1
             db.session.commit() # Commit reordering

        return jsonify({"message": "Team member deleted successfully!"})
    return jsonify({"message": "Team member not found!"}), 404

# TeamMember Move (POST)
@app.route('/api/team/<int:id>/move', methods=['POST'])
@login_required
def move_team_member(id):
    if db is None: return jsonify({"error": "Database not configured."}), 500
    if not hasattr(TeamMember, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Team Members."}), 400

    direction = request.json.get('direction')
    item_to_move = TeamMember.query.get(id)

    if not item_to_move:
        return jsonify({"message": "Team member not found!"}), 404

    all_items = TeamMember.query.order_by(TeamMember.order_id).all()
    current_index = -1
    for i, item in enumerate(all_items):
        if item.id == id:
            current_index = i
            break

    if current_index == -1:
         return jsonify({"message": "Team member not found in ordered list!"}), 404

    target_index = -1
    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction.'}), 200

    if target_index != -1:
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
        for index, item in enumerate(all_items):
            item.order_id = index + 1
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Team member moved successfully.'})
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction.'}), 200


@app.route('/api/contact', methods=['POST'])
@login_required
def update_contact():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    contact = Contact.query.first()
    if not contact:
        # Create if it doesn't exist
        contact = Contact(
            location=data.get('location', ''),
            email=data.get('email', ''),
            phone=data.get('phone', '')
        )
        db.session.add(contact)
    else:
        # Update existing
        contact.location = data.get('location', contact.location)
        contact.email = data.get('email', contact.email)
        contact.phone = data.get('phone', contact.phone)
    db.session.commit()
    return jsonify({"message": "Contact updated successfully!"})

@app.route('/api/footer', methods=['POST'])
@login_required
def update_footer():
    if db is None: return jsonify({"error": "Database not configured."}), 500
    data = request.json
    footer = Footer.query.first()
    if not footer:
        # Create if it doesn't exist
        footer = Footer(
            address=data.get('address', ''),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            linkedin=data.get('linkedin', None), # Use None for nullable fields
            github=data.get('github', None),
            twitter=data.get('twitter', None)
        )
        db.session.add(footer)
    else:
        # Update existing
        footer.address = data.get('address', footer.address)
        footer.email = data.get('email', footer.email)
        footer.phone = data.get('phone', footer.phone)
        footer.linkedin = data.get('linkedin', footer.linkedin) # Use get with existing value as default
        footer.github = data.get('github', footer.github)
        footer.twitter = data.get('twitter', footer.twitter)
    db.session.commit()
    return jsonify({"message": "Footer updated successfully!"})


# --- Local Development Server ---
# This block is executed only when you run `python app.py` directly.
# When deployed to Vercel, this block is ignored.
if __name__ == '__main__':
    # Use Flask's built-in development server
    # Ensure debug=True for development to get reloader and debugger
    print("Running Flask app locally...")
    app.run(debug=True)