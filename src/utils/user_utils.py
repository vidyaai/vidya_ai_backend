from sqlalchemy.orm import Session

from models import User
from services.brevo import add_contact_to_brevo


def get_or_create_user(
    db: Session,
    firebase_uid: str,
    email: str | None = None,
    name: str | None = None,
    user_type: str | None = None,
) -> User:
    """Get existing user by firebase_uid or create one if not found."""
    user = db.query(User).filter(User.firebase_uid == firebase_uid).first()
    if not user:
        name = name or ""
        user = User(
            firebase_uid=firebase_uid,
            email=email,
            name=name,
            user_type=user_type,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        if email:
            parts = name.split(" ", 1)
            add_contact_to_brevo(
                email=email,
                first_name=parts[0] if parts else "",
                last_name=parts[1] if len(parts) > 1 else "",
            )
    return user
