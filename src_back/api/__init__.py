"""Blueprint exports, re-exported here so the app factory imports one module."""

from src_back.api.audit_logs import bp as audit_logs_bp
from src_back.api.auth import bp as auth_bp
from src_back.api.health import bp as health_bp
from src_back.api.users import bp as users_bp

__all__ = ['audit_logs_bp', 'auth_bp', 'health_bp', 'users_bp']
