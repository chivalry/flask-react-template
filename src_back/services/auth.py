from src_back.extensions import db
from src_back.models import User


def register_user(email: str, password: str) -> User:
    if User.query.filter_by(email=email).first():
        raise ValueError("Email already registered.")
    user = User(email=email, role="user")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def authenticate_user(email: str, password: str) -> User | None:
    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        return user
    return None
