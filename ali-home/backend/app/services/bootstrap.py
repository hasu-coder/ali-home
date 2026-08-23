import json

from sqlalchemy.orm import Session

from app.models.entities import ActivityLog, Pet, Room, UserProfile


DEFAULT_ROOMS = [
    ("entrada", "Entrada", "planta_baja", ["recibidor"], True),
    ("cocina_salon", "Cocina + salón", "planta_baja", ["cocina", "salón bajo", "zona baja"], True),
    ("salon_entresuelo", "Salón entresuelo", "entresuelo", ["salón", "entresuelo"], True),
    ("bano", "Baño", "planta_superior", ["baño"], False),
    ("vestidor", "Vestidor", "planta_superior", ["closet"], False),
    ("dormitorio_matrimonio", "Dormitorio matrimonio", "planta_superior", ["dormitorio", "habitación"], True),
    ("habitacion_bebe", "Habitación bebé", "planta_superior", ["bebé"], False),
]


def seed_database(db: Session) -> None:
    for username, display in [("ismael", "Ismael"), ("laura", "Laura")]:
        if not db.query(UserProfile).filter_by(username=username).first():
            db.add(UserProfile(username=username, display_name=display))

    for key, name, floor, aliases, has_voice in DEFAULT_ROOMS:
        if not db.query(Room).filter_by(key=key).first():
            db.add(Room(key=key, name=name, floor=floor, aliases=json.dumps(aliases), has_voice_point=has_voice))

    if not db.query(Pet).filter_by(key="cat").first():
        db.add(Pet(key="cat", species="cat", name="Gato", home_state="HOME"))

    if not db.query(ActivityLog).first():
        db.add(
            ActivityLog(
                level=1,
                source="system",
                action="bootstrap",
                result="success",
                event_type="system.bootstrap",
                summary="ALI Core initialized as a local runtime.",
                details=json.dumps({"phase": 1}),
            )
        )

    db.commit()
