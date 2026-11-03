"""Initialise the database, default admin settings and (optionally) the admin account.
Usage:  python -m database.seed            (reads ADMIN_USERNAME / ADMIN_PASSWORD from env)"""
import os
from app import create_app
from services import settings_service, auth_service
from database.db import Session
from database.migrate import run_migrations


def main():
    app = create_app()
    with app.app_context():
        run_migrations()
        settings_service.ensure_defaults()
        u, p = os.getenv("ADMIN_USERNAME", ""), os.getenv("ADMIN_PASSWORD", "")
        if u and p:
            print(auth_service.create_admin(u, p))
        else:
            print("Database ready. Set ADMIN_USERNAME/ADMIN_PASSWORD and run `flask --app app create-admin` to provision the admin.")

if __name__ == "__main__":
    main()
