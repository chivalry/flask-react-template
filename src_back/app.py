import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from src_back.extensions import db, login_manager, migrate

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__, static_folder="../dist", static_url_path="/")

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///dev.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get(
        "SESSION_COOKIE_SAMESITE", "Lax"
    )
    app.config["SESSION_COOKIE_SECURE"] = (
        os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    )

    db.init_app(app)
    migrate.init_app(app, db)

    allowed_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
    CORS(app, origins=allowed_origins, supports_credentials=True)

    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        from src_back.models import User

        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify({"error": "Unauthorized"}), 401

    from src_back.api import auth_bp, health_bp

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")

    @app.errorhandler(400)
    def bad_request_handler(_e):
        return jsonify({"error": "Bad request"}), 400

    @app.errorhandler(403)
    def forbidden_handler(_e):
        return jsonify({"error": "Forbidden"}), 403

    @app.errorhandler(404)
    def not_found_handler(_e):
        if request.path.startswith("/api"):
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(app.static_folder, "index.html")

    @app.errorhandler(500)
    def server_error_handler(_e):
        return jsonify({"error": "Internal server error"}), 500

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app
