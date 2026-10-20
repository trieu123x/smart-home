"""Compatibility entrypoint: uvicorn server:app --host 127.0.0.1 --port 8000"""
from fallguard.server import app, create_app
