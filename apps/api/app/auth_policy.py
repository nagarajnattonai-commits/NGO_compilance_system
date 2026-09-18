import os
from sqlalchemy.orm import object_session
from .auth_models import AuthAccount

def is_platform_admin(user):
    allowed={x.strip().lower() for x in os.getenv("PLATFORM_ADMIN_EMAILS","").split(",") if x.strip()}
    db=object_session(user)
    account=db.get(AuthAccount,user.id) if db else None
    # Legacy identities remain eligible; new public identities need operator provisioning.
    return getattr(user,"_admin_audience",True) and getattr(user,"_platform_host",True) and getattr(user,"_identity_role",user.role)=="ADMIN" and user.email.lower() in allowed and (account is None or account.platform_access and account.verified)
