from app.database import engine, Base
import app.models  # IMPORTANT (register models)

Base.metadata.create_all(bind=engine)

print("Tables created ✅")