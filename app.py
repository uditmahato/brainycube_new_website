from flask import Flask, render_template, request, jsonify, redirect, url_for, make_response, session
import json
import os
from extensions import db
# Assuming these models exist and WhyChoose has 'order_id'
from models import Header, Banner, About, WhyChoose, Highlight, Service, Event, TeamMember, Contact, Footer
import firebase_admin
from firebase_admin import auth, credentials
from functools import wraps
from sqlalchemy import func # Needed for max order_id
from flask_migrate import Migrate # <-- Import Migrate

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', '8f4d2c9a5e7b1d3f9c0e2a8b6d4f5e7c1a3b9d2e4f6')  # Replace fallback with your generated key

# Load Firebase Admin SDK credentials
try: # Update with your file name
    # Make sure the Firebase Admin SDK JSON file is in the same directory or specify the path
    cred_path = 'brainycuberesearchorganization-firebase-adminsdk-fbsvc-413acb7eda.json'
    if not os.path.exists(cred_path):
        print(f"Firebase credentials file not found at: {cred_path}")
        print("Please make sure 'brainycuberesearchorganization-firebase-adminsdk-fbsvc-413acb7eda.json' is in the correct location.")
        # Optionally exit or raise an error here if credentials are required
        # sys.exit("Firebase credentials file missing.")
        # For now, let's just print and hope it's handled externally or isn't critical for initial run
        # Raising the exception is better for production readiness
        raise FileNotFoundError(f"Firebase credentials file not found at {cred_path}")

    cred = credentials.Certificate(cred_path) # Update with your file name
    firebase_admin.initialize_app(cred)
    print("Firebase Admin SDK initialized successfully.")
except FileNotFoundError as e:
    print(f"Initialization skipped due to missing credentials file: {e}")
    # Handle the error appropriately, maybe disable auth features
    firebase_admin = None # Indicate firebase is not available
    auth = None
except Exception as e:
    print(f"Error initializing Firebase Admin SDK: {str(e)}")
    # Handle other potential errors during initialization
    firebase_admin = None # Indicate firebase is not available
    auth = None
    # Depending on criticality, you might want to raise here too
    # raise


# Load database configuration from config.json
try:
    with open('config.json', 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    print("config.json not found. Please create it with your database credentials.")
    # Provide dummy config or exit
    config = {'user': 'user', 'password': 'password', 'database': 'database'} # Dummy values
    # raise

# Configure PostgreSQL connection
# Ensure you have psycopg2 installed (`pip install psycopg2-binary`)
app.config['SQLALCHEMY_DATABASE_URI'] = f"postgresql://{config['user']}:{config['password']}@127.0.0.1:5432/{config['database']}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy with app
db.init_app(app)

# Initialize Flask-Migrate AFTER app and db are initialized
# Only initialize if db was successfully initialized
if db:
    migrate = Migrate(app, db) # <-- Initialize Migrate
    print("Flask-Migrate initialized.")
else:
    print("Flask-Migrate initialization skipped as database is not configured.")
    migrate = None # Indicate migrate is not available
    
# Create database tables within the app context
with app.app_context():
    try:
        db.create_all()
        print("Database tables checked/created successfully.")
    except Exception as e:
        print(f"Error creating database tables: {str(e)}")
        # Handle DB connection errors on startup if necessary
        # raise

# Middleware to protect routes
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if auth is None:
             print("Firebase Auth not initialized. Skipping authentication.")
             # In a real app, you might want to redirect or return error
             # For this example, let's allow access if auth isn't configured
             # return redirect(url_for('login')) # Or jsonify({"error": "Authentication not configured"}), 500
             # If you *must* have auth, uncomment the above or raise an error
             pass # Allow access if auth is not initialized

        # Check for session cookie ONLY if auth is initialized
        if auth:
            id_token = request.cookies.get('token')
            if not id_token:
                print("No session cookie found in request")
                if request.path.startswith('/api/'):
                    return jsonify({"error": "Unauthorized: No session cookie found"}), 401
                return redirect(url_for('login'))

            try:
                # Verify the session cookie
                # clock_skew_seconds can be adjusted if needed, but default is usually fine
                decoded_token = auth.verify_session_cookie(id_token, check_revoked=True)
                print(f"Session cookie verified successfully for user: {decoded_token.get('email', 'unknown')}")
                request.user = decoded_token # Attach user info to request
            except (auth.InvalidSessionCookieError, auth.RevokedSessionCookieError) as e:
                print(f"Session cookie verification failed: {type(e).__name__} - {str(e)}")
                if request.path.startswith('/api/'):
                    return jsonify({"error": f"Unauthorized: Invalid or expired session cookie - {str(e)}"}), 401
                response = make_response(redirect(url_for('login')))
                response.set_cookie('token', '', expires=0) # Clear invalid cookie
                return response
            except Exception as e:
                print(f"Unexpected error verifying session cookie: {str(e)}")
                if request.path.startswith('/api/'):
                    return jsonify({"error": f"Unauthorized: Verification failed - {str(e)}"}), 401
                response = make_response(redirect(url_for('login')))
                response.set_cookie('token', '', expires=0) # Clear potentially problematic cookie
                return response
        # If auth was not initialized or verification passed, proceed
        return f(*args, **kwargs)
    return decorated_function

# Login page route
@app.route('/login', methods=['GET'])
def login():
    # Only render login if auth is configured, otherwise maybe show an error page or proceed
    if auth is None:
         return "Authentication is not configured. Cannot access login.", 500 # Or render a different template

    return render_template('login.html')

# Route to set session cookie after Firebase Authentication
@app.route('/sessionLogin', methods=['POST'])
def session_login():
    if auth is None:
         return jsonify({'error': 'Authentication is not configured'}), 500

    id_token = request.json.get('idToken')
    if not id_token:
        print("No ID token provided in /sessionLogin request")
        return jsonify({'error': 'No ID token provided'}), 401

    try:
        # Set session expiration to 5 days. The expiry time for the session cookie.
        # It can be a maximum of 2 weeks.
        expires_in = 60 * 60 * 24 * 5
        session_cookie = auth.create_session_cookie(id_token, expires_in=expires_in)
        print("Session cookie created successfully")

        response = make_response(jsonify({'status': 'success'}))
        # Set cookie policy. `secure=True` and `samesite='Strict'` recommended in production over HTTPS.
        # `httponly=True` prevents JavaScript access, reducing XSS risk.
        response.set_cookie('token', session_cookie, max_age=expires_in, httponly=True, secure=False) # Set secure=True in production with HTTPS
        return response
    except Exception as e:
        print(f"Error creating session cookie: {str(e)}")
        return jsonify({'error': str(e)}), 401

# Logout route
@app.route('/logout', methods=['POST'])
def logout():
    print("Logging out user")
    # Invalidate session cookie if using Firebase session cookies
    # Note: This does NOT invalidate the client-side ID token used for initial session creation.
    # For full revocation, you might need client-side sign out AND server-side revocation.
    # If using session cookies, server-side `verify_session_cookie` with `check_revoked=True`
    # is the primary protection mechanism after setting the cookie.
    # If you implement explicit token revocation lists, handle that here.
    # For now, just clear the cookie.
    response = make_response(jsonify({'status': 'success'}))
    response.set_cookie('token', '', expires=0)
    return response


# --- Website Routes ---
@app.route('/')
def index():
    # Fetch data for the public website view
    # It's generally okay to fetch all required data here for the initial render
    # If data gets very large, consider pagination or lazy loading
    header = Header.query.first()
    banner = Banner.query.first()
    about = About.query.first()
    # Fetch WhyChoose ordered by order_id
    why_choose = WhyChoose.query.order_by(WhyChoose.order_id).all()
    # Fetch Highlights ordered by order_id (assuming Highlight also has order_id)
    highlights = Highlight.query.order_by(Highlight.order_id).all() if hasattr(Highlight, 'order_id') else Highlight.query.all()
    # Fetch Services ordered by order_id (assuming Service also has order_id)
    # Exclude the additional services entry
    services = Service.query.filter_by(is_additional=False).order_by(Service.order_id).all() if hasattr(Service, 'order_id') else Service.query.filter_by(is_additional=False).all()
    additional_services_entry = Service.query.filter_by(is_additional=True).first()
    additional_services_text = additional_services_entry.additional_services if additional_services_entry else ''
    # Fetch Events ordered by order_id (assuming Event also has order_id)
    events = Event.query.order_by(Event.order_id).all() if hasattr(Event, 'order_id') else Event.query.all()
    # Fetch Team Members ordered by order_id (assuming TeamMember also has order_id)
    team = TeamMember.query.order_by(TeamMember.order_id).all() if hasattr(TeamMember, 'order_id') else TeamMember.query.all()
    contact = Contact.query.first()
    footer = Footer.query.first()

    return render_template('index.html',
                          header=header, banner=banner, about=about,
                          why_choose=why_choose, highlights=highlights,
                          services=services, additional_services=additional_services_text,
                          events=events, team=team, contact=contact, footer=footer)

# --- CMS Route ---
@app.route('/cms')
@login_required # Protect the CMS route
def cms():
    # The CMS template will fetch specific data via API calls after loading
    return render_template('cms.html')

# --- API Endpoints for CMS ---

# GET Endpoints to fetch existing data (NEW or MODIFIED)

@app.route('/api/header', methods=['GET'])
@login_required
def get_header():
    header = Header.query.first()
    if header:
        return jsonify({"logo": header.logo})
    return jsonify({"logo": ""}) # Return default empty data

@app.route('/api/banner', methods=['GET'])
@login_required
def get_banner():
    banner = Banner.query.first()
    if banner:
        return jsonify({"title": banner.title, "subtitle": banner.subtitle, "image": banner.image})
    return jsonify({"title": "", "subtitle": "", "image": ""}) # Return default empty data

@app.route('/api/about', methods=['GET'])
@login_required
def get_about():
    about = About.query.first()
    if about:
        return jsonify({
            "description": about.description,
            "logo": about.logo,
            "collaborators": about.collaborators,
            "students": about.students,
            "projects": about.projects,
            "clicks": about.clicks
        })
    return jsonify({ # Return default empty data
        "description": "",
        "logo": "",
        "collaborators": 0,
        "students": 0,
        "projects": 0,
        "clicks": 0
    })

# GET for WhyChoose already existed, but ensure it orders
@app.route('/api/why_choose', methods=['GET'])
@login_required
def get_why_choose():
    # Ensure fetching by order_id
    why_choose = WhyChoose.query.order_by(WhyChoose.order_id).all()
    return jsonify([{"id": wc.id, "title": wc.title, "icon": wc.icon, "description": wc.description, "order_id": wc.order_id} for wc in why_choose])

# GET for Highlights already existed, ensure ordering if order_id added
@app.route('/api/highlight', methods=['GET'])
@login_required
def get_highlights():
    # Ensure fetching by order_id if it exists
    highlights = Highlight.query.order_by(Highlight.order_id).all() if hasattr(Highlight, 'order_id') else Highlight.query.all()
    return jsonify([{"id": h.id, "image": h.image, "order_id": h.order_id if hasattr(h, 'order_id') else None} for h in highlights])

# GET for Services already existed, ensure ordering and filter
@app.route('/api/service', methods=['GET'])
@login_required
def get_services():
    # Ensure fetching by order_id if it exists, filter out additional services
    services = Service.query.filter_by(is_additional=False).order_by(Service.order_id).all() if hasattr(Service, 'order_id') else Service.query.filter_by(is_additional=False).all()
    return jsonify([{"id": s.id, "title": s.title, "icon": s.icon, "description": s.description, "order_id": s.order_id if hasattr(s, 'order_id') else None} for s in services])

# GET for Additional Services (NEW)
@app.route('/api/additional_services', methods=['GET'])
@login_required
def get_additional_services():
    additional = Service.query.filter_by(is_additional=True).first()
    if additional:
        return jsonify({"additional_services": additional.additional_services})
    # Create the entry if it doesn't exist? Or just return empty?
    # Let's create it with default empty data if it's missing for easier frontend logic
    try:
        additional = Service(title="Additional Services", icon="", description="", additional_services="", is_additional=True)
        db.session.add(additional)
        db.session.commit()
        return jsonify({"additional_services": ""}) # Return empty string after creating
    except Exception as e:
        print(f"Error creating default Additional Services entry: {e}")
        db.session.rollback()
        return jsonify({"additional_services": ""}) # Still return empty on error


# GET for Events already existed, ensure ordering if order_id added
@app.route('/api/event', methods=['GET'])
@login_required
def get_events():
    # Ensure fetching by order_id if it exists
    events = Event.query.order_by(Event.order_id).all() if hasattr(Event, 'order_id') else Event.query.all()
    return jsonify([{"id": e.id, "title": e.title, "year": e.year, "image": e.image, "order_id": e.order_id if hasattr(e, 'order_id') else None} for e in events])


# GET for Team already existed, ensure ordering if order_id added
@app.route('/api/team', methods=['GET'])
@login_required
def get_team():
    # Ensure fetching by order_id if it exists
    team = TeamMember.query.order_by(TeamMember.order_id).all() if hasattr(TeamMember, 'order_id') else TeamMember.query.all()
    return jsonify([{"id": t.id, "name": t.name, "title": t.title, "bio": t.bio,
                     "image": t.image, "linkedin": t.linkedin, "github": t.github, "order_id": t.order_id if hasattr(t, 'order_id') else None} for t in team])

@app.route('/api/contact', methods=['GET'])
@login_required
def get_contact():
    contact = Contact.query.first()
    if contact:
        return jsonify({"location": contact.location, "email": contact.email, "phone": contact.phone})
    return jsonify({"location": "", "email": "", "phone": ""}) # Return default empty data

@app.route('/api/footer', methods=['GET'])
@login_required
def get_footer():
    footer = Footer.query.first()
    if footer:
        return jsonify({"address": footer.address, "email": footer.email, "phone": footer.phone,
                       "linkedin": footer.linkedin, "github": footer.github, "twitter": footer.twitter})
    return jsonify({ # Return default empty data
        "address": "",
        "email": "",
        "phone": "",
        "linkedin": "",
        "github": "",
        "twitter": ""
    })


# POST/PUT/DELETE Endpoints (Adjusted for SQLAlchemy and ordering)

@app.route('/api/header', methods=['POST'])
@login_required
def update_header():
    data = request.json
    header = Header.query.first()
    if not header:
        header = Header(logo=data.get('logo', '')) # Use .get for safety
        db.session.add(header)
    else:
        header.logo = data.get('logo', header.logo) # Update or keep existing if key missing
    db.session.commit()
    return jsonify({"message": "Header updated successfully!"})

@app.route('/api/banner', methods=['POST'])
@login_required
def update_banner():
    data = request.json
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
        banner.image = data.get('image', banner.image) # Allow image to be updated
    db.session.commit()
    return jsonify({"message": "Banner updated successfully!"})

@app.route('/api/about', methods=['POST'])
@login_required
def update_about():
    data = request.json
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

# WhyChoose Add (POST) - Modified to set order_id
@app.route('/api/why_choose', methods=['POST'])
@login_required
def add_why_choose():
    data = request.json
    # Get the maximum current order_id and add 1 for the new item
    max_order = db.session.query(func.max(WhyChoose.order_id)).scalar() or 0
    new_order_id = max_order + 1

    why_choose = WhyChoose(
        title=data.get('title', ''),
        icon=data.get('icon', ''),
        description=data.get('description', ''),
        order_id=new_order_id # Set the order_id
    )
    db.session.add(why_choose)
    db.session.commit()
    # Return the new item's ID and order_id in the response
    return jsonify({"message": "Why Choose card added successfully!", "id": why_choose.id, "order_id": why_choose.order_id}), 201 # 201 Created

# WhyChoose Update (PUT - NEW)
@app.route('/api/why_choose/<int:id>', methods=['PUT'])
@login_required
def update_why_choose(id):
    data = request.json
    why_choose = WhyChoose.query.get(id)
    if why_choose:
        why_choose.title = data.get('title', why_choose.title)
        why_choose.icon = data.get('icon', why_choose.icon)
        why_choose.description = data.get('description', why_choose.description)
        # order_id is handled by the move endpoint, don't update it here
        db.session.commit()
        return jsonify({"message": "Why Choose card updated successfully!"})
    return jsonify({"message": "Card not found!"}), 404


# WhyChoose Delete (DELETE)
@app.route('/api/why_choose/<int:id>', methods=['DELETE'])
@login_required
def delete_why_choose(id):
    why_choose = WhyChoose.query.get(id)
    if why_choose:
        db.session.delete(why_choose)
        # Reorder remaining items after deletion (optional but good practice)
        # Get all items with order_id > deleted item's order_id
        items_to_reorder = WhyChoose.query.filter(WhyChoose.order_id > why_choose.order_id).order_by(WhyChoose.order_id).all()
        # Decrement their order_id
        for item in items_to_reorder:
            item.order_id -= 1
        db.session.commit()
        return jsonify({"message": "Why Choose card deleted successfully!"})
    return jsonify({"message": "Card not found!"}), 404

# WhyChoose Move (POST) - Refactored to use SQLAlchemy
@app.route('/api/why_choose/<int:id>/move', methods=['POST'])
@login_required
def move_why_choose(id):
    direction = request.json.get('direction')
    item_to_move = WhyChoose.query.get(id)

    if not item_to_move:
        return jsonify({"message": "Card not found!"}), 404

    all_items = WhyChoose.query.order_by(WhyChoose.order_id).all()
    current_index = -1
    for i, item in enumerate(all_items):
        if item.id == id:
            current_index = i
            break

    if current_index == -1: # Should not happen if get(id) worked, but safe check
         return jsonify({"message": "Card not found in ordered list!"}), 404

    target_index = -1
    if direction == 'up' and current_index > 0:
        target_index = current_index - 1
    elif direction == 'down' and current_index < len(all_items) - 1:
        target_index = current_index + 1
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction'}), 200 # Or 400 if invalid direction

    if target_index != -1:
        # Swap the order_ids between the two items
        item1 = all_items[current_index]
        item2 = all_items[target_index]

        # Simple swap is often enough if order_ids are contiguous (which renumbering ensures)
        # Ensure order_ids are unique before swapping, or use a temporary value
        # A more robust method re-assigns all order_ids based on the new list order
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]

        # Reassign order_ids based on the new list order
        for index, item in enumerate(all_items):
            item.order_id = index + 1 # Start order_id from 1

        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Why Choose card moved successfully'})
    else:
        # This case should be caught by the checks above, but as a fallback
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction'}), 200


# Highlight Add (POST) - Modified to set order_id (assuming order_id exists)
@app.route('/api/highlight', methods=['POST'])
@login_required
def add_highlight():
    data = request.json
    # Assuming Highlight model has order_id
    max_order = db.session.query(func.max(Highlight.order_id)).scalar() or 0 if hasattr(Highlight, 'order_id') else 0
    new_order_id = max_order + 1

    highlight = Highlight(image=data.get('image', ''))
    if hasattr(Highlight, 'order_id'):
         highlight.order_id = new_order_id

    db.session.add(highlight)
    db.session.commit()
    return jsonify({"message": "Highlight added successfully!", "id": highlight.id}), 201 # 201 Created

# Highlight Update (PUT - NEW)
@app.route('/api/highlight/<int:id>', methods=['PUT'])
@login_required
def update_highlight(id):
    data = request.json
    highlight = Highlight.query.get(id)
    if highlight:
        highlight.image = data.get('image', highlight.image)
        db.session.commit()
        return jsonify({"message": "Highlight updated successfully!"})
    return jsonify({"message": "Highlight not found!"}), 404

# Highlight Delete (DELETE) - Modified for potential order_id
@app.route('/api/highlight/<int:id>', methods=['DELETE'])
@login_required
def delete_highlight(id):
    highlight = Highlight.query.get(id)
    if highlight:
        deleted_order_id = highlight.order_id if hasattr(highlight, 'order_id') else None
        db.session.delete(highlight)
        db.session.commit() # Commit deletion first

        # Reorder remaining items if order_id exists
        if deleted_order_id is not None:
            items_to_reorder = Highlight.query.filter(Highlight.order_id > deleted_order_id).order_by(Highlight.order_id).all()
            for item in items_to_reorder:
                item.order_id -= 1
            db.session.commit()

        return jsonify({"message": "Highlight deleted successfully!"})
    return jsonify({"message": "Highlight not found!"}), 404

# Highlight Move (POST - NEW) - Implement move logic for Highlights if order_id exists
@app.route('/api/highlight/<int:id>/move', methods=['POST'])
@login_required
def move_highlight(id):
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
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction'}), 200

    if target_index != -1:
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
        for index, item in enumerate(all_items):
            item.order_id = index + 1
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Highlight moved successfully'})
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction'}), 200


# Service Add (POST) - Modified to set order_id (assuming order_id exists)
@app.route('/api/service', methods=['POST'])
@login_required
def add_service():
    data = request.json
    # Ensure we only add regular services here
    if data.get('is_additional', False):
        return jsonify({"message": "Use the additional services endpoint for that."}), 400

    # Assuming Service model has order_id
    max_order = db.session.query(func.max(Service.order_id)).filter_by(is_additional=False).scalar() or 0 if hasattr(Service, 'order_id') else 0
    new_order_id = max_order + 1

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
    return jsonify({"message": "Service added successfully!", "id": service.id}), 201

# Service Update (PUT - NEW)
@app.route('/api/service/<int:id>', methods=['PUT'])
@login_required
def update_service(id):
    data = request.json
    service = Service.query.get(id)
    if service and not service.is_additional: # Don't update additional service via this endpoint
        service.title = data.get('title', service.title)
        service.icon = data.get('icon', service.icon)
        service.description = data.get('description', service.description)
        db.session.commit()
        return jsonify({"message": "Service updated successfully!"})
    return jsonify({"message": "Service not found or is an additional service entry!"}), 404


# Service Delete (DELETE) - Modified for potential order_id
@app.route('/api/service/<int:id>', methods=['DELETE'])
@login_required
def delete_service(id):
    service = Service.query.get(id)
    if service and not service.is_additional:
        deleted_order_id = service.order_id if hasattr(service, 'order_id') else None
        db.session.delete(service)
        db.session.commit() # Commit deletion first

        # Reorder remaining items if order_id exists
        if deleted_order_id is not None:
             items_to_reorder = Service.query.filter_by(is_additional=False).filter(Service.order_id > deleted_order_id).order_by(Service.order_id).all()
             for item in items_to_reorder:
                 item.order_id -= 1
             db.session.commit()

        return jsonify({"message": "Service deleted successfully!"})
    return jsonify({"message": "Service not found or is an additional service entry!"}), 404

# Service Move (POST - NEW) - Implement move logic for Services if order_id exists
@app.route('/api/service/<int:id>/move', methods=['POST'])
@login_required
def move_service(id):
    if not hasattr(Service, 'order_id'):
        return jsonify({"message": "Ordering is not configured for Services."}), 400

    direction = request.json.get('direction')
    item_to_move = Service.query.get(id)

    if not item_to_move or item_to_move.is_additional:
        return jsonify({"message": "Service not found or is an additional service entry!"}), 404

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
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction'}), 200

    if target_index != -1:
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
        for index, item in enumerate(all_items):
            item.order_id = index + 1
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Service moved successfully'})
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction'}), 200


# Additional Services Update (POST)
@app.route('/api/additional_services', methods=['POST'])
@login_required
def update_additional_services():
    data = request.json
    additional = Service.query.filter_by(is_additional=True).first()
    if not additional:
        # Create it if it doesn't exist
        additional = Service(title="Additional Services", icon="", description="", additional_services=data.get('additional_services', ''), is_additional=True)
        # order_id for this specific entry can be set arbitrarily, e.g., 0, or ignored if always fetched separately
        if hasattr(Service, 'order_id'):
             additional.order_id = 0 # Assign a fixed low order_id or handle differently
        db.session.add(additional)
    else:
        additional.additional_services = data.get('additional_services', additional.additional_services)
    db.session.commit()
    return jsonify({"message": "Additional Services updated successfully!"})

# Event Add (POST) - Modified to set order_id (assuming order_id exists)
@app.route('/api/event', methods=['POST'])
@login_required
def add_event():
    data = request.json
     # Assuming Event model has order_id
    max_order = db.session.query(func.max(Event.order_id)).scalar() or 0 if hasattr(Event, 'order_id') else 0
    new_order_id = max_order + 1

    event = Event(
        title=data.get('title', ''),
        year=data.get('year', ''),
        image=data.get('image', '')
    )
    if hasattr(Event, 'order_id'):
         event.order_id = new_order_id

    db.session.add(event)
    db.session.commit()
    return jsonify({"message": "Event added successfully!", "id": event.id}), 201

# Event Update (PUT - NEW)
@app.route('/api/event/<int:id>', methods=['PUT'])
@login_required
def update_event(id):
    data = request.json
    event = Event.query.get(id)
    if event:
        event.title = data.get('title', event.title)
        event.year = data.get('year', event.year)
        event.image = data.get('image', event.image)
        db.session.commit()
        return jsonify({"message": "Event updated successfully!"})
    return jsonify({"message": "Event not found!"}), 404

# Event Delete (DELETE) - Modified for potential order_id
@app.route('/api/event/<int:id>', methods=['DELETE'])
@login_required
def delete_event(id):
    event = Event.query.get(id)
    if event:
        deleted_order_id = event.order_id if hasattr(event, 'order_id') else None
        db.session.delete(event)
        db.session.commit() # Commit deletion first

        # Reorder remaining items if order_id exists
        if deleted_order_id is not None:
             items_to_reorder = Event.query.filter(Event.order_id > deleted_order_id).order_by(Event.order_id).all()
             for item in items_to_reorder:
                 item.order_id -= 1
             db.session.commit()

        return jsonify({"message": "Event deleted successfully!"})
    return jsonify({"message": "Event not found!"}), 404

# Event Move (POST - NEW) - Implement move logic for Events if order_id exists
@app.route('/api/event/<int:id>/move', methods=['POST'])
@login_required
def move_event(id):
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
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction'}), 200

    if target_index != -1:
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
        for index, item in enumerate(all_items):
            item.order_id = index + 1
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Event moved successfully'})
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction'}), 200


# TeamMember Add (POST) - Modified to set order_id (assuming order_id exists)
@app.route('/api/team', methods=['POST'])
@login_required
def add_team_member():
    data = request.json
     # Assuming TeamMember model has order_id
    max_order = db.session.query(func.max(TeamMember.order_id)).scalar() or 0 if hasattr(TeamMember, 'order_id') else 0
    new_order_id = max_order + 1

    team_member = TeamMember(
        name=data.get('name', ''),
        title=data.get('title', ''),
        bio=data.get('bio', ''),
        image=data.get('image', ''),
        linkedin=data.get('linkedin', ''),
        github=data.get('github', '')
    )
    if hasattr(TeamMember, 'order_id'):
         team_member.order_id = new_order_id

    db.session.add(team_member)
    db.session.commit()
    return jsonify({"message": "Team member added successfully!", "id": team_member.id}), 201

# TeamMember Update (PUT - NEW)
@app.route('/api/team/<int:id>', methods=['PUT'])
@login_required
def update_team_member(id):
    data = request.json
    team_member = TeamMember.query.get(id)
    if team_member:
        team_member.name = data.get('name', team_member.name)
        team_member.title = data.get('title', team_member.title)
        team_member.bio = data.get('bio', team_member.bio)
        team_member.image = data.get('image', team_member.image)
        team_member.linkedin = data.get('linkedin', team_member.linkedin)
        team_member.github = data.get('github', team_member.github)
        db.session.commit()
        return jsonify({"message": "Team member updated successfully!"})
    return jsonify({"message": "Team member not found!"}), 404

# TeamMember Delete (DELETE) - Modified for potential order_id
@app.route('/api/team/<int:id>', methods=['DELETE'])
@login_required
def delete_team_member(id):
    team_member = TeamMember.query.get(id)
    if team_member:
        deleted_order_id = team_member.order_id if hasattr(team_member, 'order_id') else None
        db.session.delete(team_member)
        db.session.commit() # Commit deletion first

        # Reorder remaining items if order_id exists
        if deleted_order_id is not None:
             items_to_reorder = TeamMember.query.filter(TeamMember.order_id > deleted_order_id).order_by(TeamMember.order_id).all()
             for item in items_to_reorder:
                 item.order_id -= 1
             db.session.commit()

        return jsonify({"message": "Team member deleted successfully!"})
    return jsonify({"message": "Team member not found!"}), 404

# TeamMember Move (POST - NEW) - Implement move logic for TeamMembers if order_id exists
@app.route('/api/team/<int:id>/move', methods=['POST'])
@login_required
def move_team_member(id):
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
        return jsonify({'status': 'info', 'message': 'Cannot move further in this direction'}), 200

    if target_index != -1:
        all_items[current_index], all_items[target_index] = all_items[target_index], all_items[current_index]
        for index, item in enumerate(all_items):
            item.order_id = index + 1
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Team member moved successfully'})
    else:
        return jsonify({'status': 'info', 'message': 'Cannot move in this direction'}), 200


@app.route('/api/contact', methods=['POST'])
@login_required
def update_contact():
    data = request.json
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
    data = request.json
    footer = Footer.query.first()
    if not footer:
        footer = Footer(
            address=data.get('address', ''),
            email=data.get('email', ''),
            phone=data.get('phone', ''),
            linkedin=data.get('linkedin', ''),
            github=data.get('github', ''),
            twitter=data.get('twitter', '')
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


if __name__ == '__main__':
    # Consider using a more robust server like Waitress or Gunicorn in production
    # For development, debug=True is fine
    app.run(debug=True)