import os

from dotenv import load_dotenv
from flask import Flask, send_from_directory
from flask_cors import CORS
from flask_migrate import Migrate

from src_back.models import db

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__, static_folder="../dist", static_url_path="/")

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///dev.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    Migrate(app, db)

    allowed_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
    CORS(app, origins=allowed_origins)

    from src_back.api.routes import bp as api_bp

    app.register_blueprint(api_bp, url_prefix="/api")

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.errorhandler(404)
    def not_found_handler(_e):
        return send_from_directory(app.static_folder, "index.html")

    return app
