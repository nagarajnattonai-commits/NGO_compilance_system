"""One-time, local-only ownership setup for the pre-existing workspace.

Run: python -m app.bootstrap_admin
Passwords are prompted without echo and never stored in plaintext.
"""
from getpass import getpass

from sqlalchemy import select

from .auth import EmailInput, PasswordInput, hash_password
from .database import Base, SessionLocal, engine
from .models import User, Workspace
from .seed import TENANT_ID, seed_demo_data


def main():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.tenant_id == TENANT_ID, User.role == "ADMIN")):
            raise SystemExit("An administrator already owns this workspace. Use login or password recovery.")
        name = input("Administrator name: ").strip()
        if len(name) < 2:
            raise SystemExit("Enter a name with at least two characters.")
        email = EmailInput(email=input("Administrator email: ")).email
        if db.scalar(select(User.id).where(User.email == email)):
            raise SystemExit("This email is already registered.")
        password = getpass("Password (12–128 characters): ")
        PasswordInput(password=password)
        if password != getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
        seed_demo_data(db)
        if not db.get(Workspace, TENANT_ID):
            db.add(Workspace(id=TENANT_ID, name="NGO Compliance workspace"))
        db.add(User(name=name, email=email, password_hash=hash_password(password),
                    role="ADMIN", tenant_id=TENANT_ID, status="ACTIVE"))
        db.commit()
    print("Administrator created. Sign in with your email and password. Existing data is preserved.")


if __name__ == "__main__":
    main()
