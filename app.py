from flask import Flask, render_template, request, jsonify
import json
import os
from extensions import db
from models import Header, Banner, About, WhyChoose, Highlight, Service, Event, TeamMember, Contact, Footer

# Initialize Flask app
app = Flask(__name__)

# Load database configuration from config.json
with open('config.json', 'r') as f:
    config = json.load(f)

# Configure PostgreSQL connection
app.config['SQLALCHEMY_DATABASE_URI'] = f"postgresql://{config['user']}:{config['password']}@127.0.0.1:5432/{config['database']}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize SQLAlchemy with app
db.init_app(app)

# Create database tables
with app.app_context():
    db.create_all()

# Routes for Website (index.html)
@app.route('/')
def index():
    header = Header.query.first()
    banner = Banner.query.first()
    about = About.query.first()
    why_choose = WhyChoose.query.all()
    highlights = Highlight.query.all()
    services = Service.query.all()
    additional_services = Service.query.filter_by(is_additional=True).first()
    events = Event.query.all()
    team = TeamMember.query.all()
    contact = Contact.query.first()
    footer = Footer.query.first()

    return render_template('index.html', 
                          header=header, banner=banner, about=about, 
                          why_choose=why_choose, highlights=highlights, 
                          services=services, additional_services=additional_services.additional_services if additional_services else '',
                          events=events, team=team, contact=contact, footer=footer)

# Routes for CMS (cms.html)
@app.route('/cms')
def cms():
    return render_template('cms.html')

# API Endpoints for CMS to Update Content
@app.route('/api/header', methods=['POST'])
def update_header():
    data = request.json
    header = Header.query.first()
    if not header:
        header = Header(logo=data['logo'])
        db.session.add(header)
    else:
        header.logo = data['logo']
    db.session.commit()
    return jsonify({"message": "Header updated successfully!"})

@app.route('/api/banner', methods=['POST'])
def update_banner():
    data = request.json
    banner = Banner.query.first()
    if not banner:
        banner = Banner(title=data['title'], subtitle=data['subtitle'], image=data['image'])
        db.session.add(banner)
    else:
        banner.title = data['title']
        banner.subtitle = data['subtitle']
        banner.image = data['image']
    db.session.commit()
    return jsonify({"message": "Banner updated successfully!"})

@app.route('/api/about', methods=['POST'])
def update_about():
    data = request.json
    about = About.query.first()
    if not about:
        about = About(description=data['description'], logo=data['logo'], 
                      collaborators=data['collaborators'], students=data['students'], 
                      projects=data['projects'], clicks=data['clicks'])
        db.session.add(about)
    else:
        about.description = data['description']
        about.logo = data['logo']
        about.collaborators = data['collaborators']
        about.students = data['students']
        about.projects = data['projects']
        about.clicks = data['clicks']
    db.session.commit()
    return jsonify({"message": "About Us updated successfully!"})

@app.route('/api/why_choose', methods=['POST'])
def add_why_choose():
    data = request.json
    why_choose = WhyChoose(title=data['title'], icon=data['icon'], description=data['description'])
    db.session.add(why_choose)
    db.session.commit()
    return jsonify({"message": "Why Choose card added successfully!"})

@app.route('/api/why_choose/<int:id>', methods=['DELETE'])
def delete_why_choose(id):
    why_choose = WhyChoose.query.get(id)
    if why_choose:
        db.session.delete(why_choose)
        db.session.commit()
        return jsonify({"message": "Why Choose card deleted successfully!"})
    return jsonify({"message": "Card not found!"}), 404

@app.route('/api/why_choose', methods=['GET'])
def get_why_choose():
    why_choose = WhyChoose.query.all()
    return jsonify([{"id": wc.id, "title": wc.title, "icon": wc.icon, "description": wc.description} for wc in why_choose])

@app.route('/api/highlight', methods=['POST'])
def add_highlight():
    data = request.json
    highlight = Highlight(image=data['image'])
    db.session.add(highlight)
    db.session.commit()
    return jsonify({"message": "Highlight added successfully!"})

@app.route('/api/highlight/<int:id>', methods=['DELETE'])
def delete_highlight(id):
    highlight = Highlight.query.get(id)
    if highlight:
        db.session.delete(highlight)
        db.session.commit()
        return jsonify({"message": "Highlight deleted successfully!"})
    return jsonify({"message": "Highlight not found!"}), 404

@app.route('/api/highlight', methods=['GET'])
def get_highlights():
    highlights = Highlight.query.all()
    return jsonify([{"id": h.id, "image": h.image} for h in highlights])

@app.route('/api/service', methods=['POST'])
def add_service():
    data = request.json
    service = Service(title=data['title'], icon=data['icon'], description=data['description'], is_additional=False)
    db.session.add(service)
    db.session.commit()
    return jsonify({"message": "Service added successfully!"})

@app.route('/api/service/<int:id>', methods=['DELETE'])
def delete_service(id):
    service = Service.query.get(id)
    if service:
        db.session.delete(service)
        db.session.commit()
        return jsonify({"message": "Service deleted successfully!"})
    return jsonify({"message": "Service not found!"}), 404

@app.route('/api/service', methods=['GET'])
def get_services():
    services = Service.query.filter_by(is_additional=False).all()
    return jsonify([{"id": s.id, "title": s.title, "icon": s.icon, "description": s.description} for s in services])

@app.route('/api/additional_services', methods=['POST'])
def update_additional_services():
    data = request.json
    additional = Service.query.filter_by(is_additional=True).first()
    if not additional:
        additional = Service(title="Additional Services", icon="", description="", additional_services=data['additional_services'], is_additional=True)
        db.session.add(additional)
    else:
        additional.additional_services = data['additional_services']
    db.session.commit()
    return jsonify({"message": "Additional Services updated successfully!"})

@app.route('/api/event', methods=['POST'])
def add_event():
    data = request.json
    event = Event(title=data['title'], year=data['year'], image=data['image'])
    db.session.add(event)
    db.session.commit()
    return jsonify({"message": "Event added successfully!"})

@app.route('/api/event/<int:id>', methods=['DELETE'])
def delete_event(id):
    event = Event.query.get(id)
    if event:
        db.session.delete(event)
        db.session.commit()
        return jsonify({"message": "Event deleted successfully!"})
    return jsonify({"message": "Event not found!"}), 404

@app.route('/api/event', methods=['GET'])
def get_events():
    events = Event.query.all()
    return jsonify([{"id": e.id, "title": e.title, "year": e.year, "image": e.image} for e in events])

@app.route('/api/team', methods=['POST'])
def add_team_member():
    data = request.json
    team_member = TeamMember(name=data['name'], title=data['title'], bio=data['bio'], 
                             image=data['image'], linkedin=data['linkedin'], github=data['github'])
    db.session.add(team_member)
    db.session.commit()
    return jsonify({"message": "Team member added successfully!"})

@app.route('/api/team/<int:id>', methods=['DELETE'])
def delete_team_member(id):
    team_member = TeamMember.query.get(id)
    if team_member:
        db.session.delete(team_member)
        db.session.commit()
        return jsonify({"message": "Team member deleted successfully!"})
    return jsonify({"message": "Team member not found!"}), 404

@app.route('/api/team', methods=['GET'])
def get_team():
    team = TeamMember.query.all()
    return jsonify([{"id": t.id, "name": t.name, "title": t.title, "bio": t.bio, 
                     "image": t.image, "linkedin": t.linkedin, "github": t.github} for t in team])

@app.route('/api/contact', methods=['POST'])
def update_contact():
    data = request.json
    contact = Contact.query.first()
    if not contact:
        contact = Contact(location=data['location'], email=data['email'], phone=data['phone'])
        db.session.add(contact)
    else:
        contact.location = data['location']
        contact.email = data['email']
        contact.phone = data['phone']
    db.session.commit()
    return jsonify({"message": "Contact updated successfully!"})

@app.route('/api/footer', methods=['POST'])
def update_footer():
    data = request.json
    footer = Footer.query.first()
    if not footer:
        footer = Footer(address=data['address'], email=data['email'], phone=data['phone'], 
                        linkedin=data['linkedin'], github=data['github'], twitter=data['twitter'])
        db.session.add(footer)
    else:
        footer.address = data['address']
        footer.email = data['email']
        footer.phone = data['phone']
        footer.linkedin = data['linkedin']
        footer.github = data['github']
        footer.twitter = data['twitter']
    db.session.commit()
    return jsonify({"message": "Footer updated successfully!"})

if __name__ == '__main__':
    app.run(debug=True)