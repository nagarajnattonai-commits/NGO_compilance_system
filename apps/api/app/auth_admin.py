"""Operator-only provisioning: python -m app.auth_admin --email EMAIL."""
import argparse
from sqlalchemy import select
from .database import Base,engine,SessionLocal
from .models import User
from .auth_models import AuthAccount
from .auth_policy import is_platform_admin

def grant(db,email):
    user=db.scalar(select(User).where(User.email==email.strip().lower(),User.status=="ACTIVE"))
    if not user or user.role!="ADMIN":raise ValueError("An existing active administrator identity is required")
    account=db.get(AuthAccount,user.id)
    if not account:account=AuthAccount(user_id=user.id);db.add(account)
    account.verified=True;account.verification_required=True;account.platform_access=True
    db.flush()
    if not is_platform_admin(user):raise ValueError("Identity must be explicitly listed in PLATFORM_ADMIN_EMAILS")
    db.commit()

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--email",required=True)
    parser.add_argument("--google-client-id");parser.add_argument("--google-secret-ref")
    parser.add_argument("--enable-user-google",action="store_true");parser.add_argument("--enable-signup-google",action="store_true");parser.add_argument("--enable-admin-google",action="store_true")
    args=parser.parse_args()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        grant(db,args.email)
        if args.google_client_id:
            from .auth_models import OAuthPolicy
            from .integration_security import secret_store
            if not args.google_secret_ref:raise ValueError("A secret-store reference is required")
            secret_store().get_secret_for_server_use(args.google_secret_ref)
            row=db.get(OAuthPolicy,"google")
            if not row:row=OAuthPolicy(provider="google");db.add(row)
            row.client_id=args.google_client_id;row.secret_ref=args.google_secret_ref
            row.user_enabled=args.enable_user_google;row.signup_enabled=args.enable_signup_google;row.admin_enabled=args.enable_admin_google
            db.commit()
    print("Provisioned existing platform administrator identity.")
