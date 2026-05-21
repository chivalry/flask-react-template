from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required, login_user, logout_user
from marshmallow import ValidationError

from src_back.schemas.user import LoginSchema, UserSchema, user_schema
from src_back.services.auth import authenticate_user, register_user
from src_back.utils import bad_request, conflict

bp = Blueprint("auth", __name__)

_login_schema = LoginSchema()
_user_schema = UserSchema()


@bp.post("/register")
def register():
    try:
        data = _user_schema.load(request.get_json() or {})
    except ValidationError as e:
        return bad_request(str(e.messages))
    try:
        user = register_user(data["email"], data["password"])
    except ValueError as e:
        return conflict(str(e))
    login_user(user)
    return jsonify(user_schema.dump(user)), 201


@bp.post("/login")
def login():
    try:
        data = _login_schema.load(request.get_json() or {})
    except ValidationError as e:
        return bad_request(str(e.messages))
    user = authenticate_user(data["email"], data["password"])
    if not user:
        return jsonify({"error": "Invalid email or password."}), 401
    login_user(user)
    return jsonify(user_schema.dump(user))


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Logged out."})


@bp.get("/me")
@login_required
def me():
    return jsonify(user_schema.dump(current_user))
