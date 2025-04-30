
from extensions import db

class Header(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    logo = db.Column(db.Text, nullable=False)

class Banner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    subtitle = db.Column(db.String(300), nullable=False)
    image = db.Column(db.Text, nullable=False)

class About(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text, nullable=False)
    logo = db.Column(db.Text, nullable=False)
    collaborators = db.Column(db.Integer, nullable=False)
    students = db.Column(db.Integer, nullable=False)
    projects = db.Column(db.Integer, nullable=False)
    clicks = db.Column(db.Integer, nullable=False)

class WhyChoose(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)

class Highlight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.Text, nullable=False)
class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    is_additional = db.Column(db.Boolean, default=False)
    additional_services = db.Column(db.Text)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    year = db.Column(db.String(4), nullable=False)
    image = db.Column(db.Text, nullable=False)

class TeamMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    bio = db.Column(db.Text, nullable=False)
    image = db.Column(db.Text, nullable=False)
    linkedin = db.Column(db.String(500), nullable=False)
    github = db.Column(db.String(500), nullable=False)

class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)

class Footer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    linkedin = db.Column(db.String(500), nullable=False)
    github = db.Column(db.String(500), nullable=False)
    twitter = db.Column(db.String(500), nullable=False)