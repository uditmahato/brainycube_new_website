# # minimal_app.py
# from flask import Flask
# from flask_sqlalchemy import SQLAlchemy
# from flask_migrate import Migrate
# from dotenv import load_dotenv
# import os

# load_dotenv()

# app = Flask(__name__)

# database_uri = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_URL')
# if database_uri:
#     if database_uri.startswith('postgres://'):
#         database_uri = database_uri.replace('postgres://', 'postgresql://', 1)
#     app.config['SQLALCHEMY_DATABASE_URI'] = database_uri
#     app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
#     print("Database URI:", database_uri)
# else:
#     print("No DATABASE_URL or POSTGRES_URL set.")

# db = SQLAlchemy()
# db.init_app(app)
# migrate = Migrate(app, db)

# @app.route('/')
# def index():
#     return "Test route"

# if __name__ == '__main__':
#     app.run(debug=True)


    # test_extensions.py
from extensions import db
print("db:", db)