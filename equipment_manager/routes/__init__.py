from flask import Blueprint


bp = Blueprint("web", __name__)

from . import admin, common, public, station  # noqa: E402,F401
