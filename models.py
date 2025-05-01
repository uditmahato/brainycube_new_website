from extensions import db

class Header(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    logo = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f"<Header {self.id}>"


class Banner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    subtitle = db.Column(db.String(300), nullable=False)
    image = db.Column(db.Text, nullable=False) # Storing base64 or URL

    def __repr__(self):
        return f"<Banner {self.id}: {self.title}>"


class About(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text, nullable=False) # Storing HTML potentially
    logo = db.Column(db.Text, nullable=False) # Storing base64 or URL
    collaborators = db.Column(db.Integer, nullable=False)
    students = db.Column(db.Integer, nullable=False)
    projects = db.Column(db.Integer, nullable=False)
    clicks = db.Column(db.Integer, nullable=False)

    def __repr__(self):
        return f"<About {self.id}>"


class WhyChoose(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    icon = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    # Add the order_id column for ordering
    order_id = db.Column(db.Integer, default=0, nullable=False)

    def __repr__(self):
        return f"<WhyChoose {self.id}: {self.title}>"


class Highlight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.Text, nullable=False) # Storing base64 or URL
    # Add the order_id column for ordering
    order_id = db.Column(db.Integer, default=0, nullable=False)

    def __repr__(self):
        return f"<Highlight {self.id}>"


class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Make title, icon, description nullable for the single 'additional_services' entry
    title = db.Column(db.String(100), nullable=True)
    icon = db.Column(db.String(50), nullable=True)
    description = db.Column(db.Text, nullable=True)
    is_additional = db.Column(db.Boolean, default=False, nullable=False)
    additional_services = db.Column(db.Text, nullable=True) # Only used for the is_additional=True entry
    # Add the order_id column for ordering regular services
    order_id = db.Column(db.Integer, default=0, nullable=False)


    def __repr__(self):
        return f"<Service {self.id}: {self.title or 'Additional'}>"


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    year = db.Column(db.String(4), nullable=False)
    image = db.Column(db.Text, nullable=False) # Storing base64 or URL
    # Add the order_id column for ordering
    order_id = db.Column(db.Integer, default=0, nullable=False)


    def __repr__(self):
        return f"<Event {self.id}: {self.title}>"


class TeamMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    bio = db.Column(db.Text, nullable=False)
    image = db.Column(db.Text, nullable=False) # Storing base64 or URL
    # Make social links nullable as they might be optional for some members
    linkedin = db.Column(db.String(500), nullable=True)
    github = db.Column(db.String(500), nullable=True)
     # Add the order_id column for ordering
    order_id = db.Column(db.Integer, default=0, nullable=False)


    def __repr__(self):
        return f"<TeamMember {self.id}: {self.name}>"


class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)

    def __repr__(self):
        return f"<Contact {self.id}>"


class Footer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    # Make social links nullable as they might be optional
    linkedin = db.Column(db.String(500), nullable=True)
    github = db.Column(db.String(500), nullable=True)
    twitter = db.Column(db.String(500), nullable=True)

    def __repr__(self):
        return f"<Footer {self.id}>"