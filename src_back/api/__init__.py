"""Blueprint exports, re-exported here so the app factory imports one module."""

from src_back.api.auth import bp as auth_bp
from src_back.api.health import bp as health_bp

__all__ = ['auth_bp', 'health_bp']
