from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_security import RoleMixin, Security, SQLAlchemyUserDatastore, UserMixin
from dotenv import load_dotenv, get_key

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///site.db"
app.config["SECRET_KEY"] = get_key(".env", "SECRET_KEY")
app.config["SECURITY_PASSWORD_SALT"] = get_key(".env", "SECURITY_PASSWORD_SALT")

# Config for Flask-Security
app.config["SECURITY_REGISTERABLE"] = True
app.config["SECURITY_SEND_REGISTER_EMAIL"] = False

# Initialise the database
db = SQLAlchemy(app)

# Association table linking Users and Roles
roles_users = db.Table(
    "roles_users",
    db.Column("user_id", db.Integer(), db.ForeignKey("user.id")),
    db.Column("role_id", db.Integer(), db.ForeignKey("role.id")),
)

class Role(db.Model, RoleMixin):
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(80), unique=True)
    description = db.Column(db.String(255))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean())
    fs_uniquifier = db.Column(db.String(64), unique=True, nullable=False)
    
    # MOVED: Relationship must be inside the User model
    roles = db.relationship(
        "Role", secondary=roles_users, backref=db.backref("users", lazy="dynamic")
    ) # type: ignore

user_datastore = SQLAlchemyUserDatastore(db, User, Role)
security = Security(app, user_datastore)

# Added to ensure tables are created when you start the app
with app.app_context():
    db.create_all()