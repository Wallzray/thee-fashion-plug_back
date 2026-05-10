import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base


raw_uri = os.getenv("DATABASE_URL")

if raw_uri:
    # 1. Standard Render Fix
    if raw_uri.startswith("postgres://"):
        raw_uri = raw_uri.replace("postgres://", "postgresql://", 1)
    
    # 2. Force SQLAlchemy to use the pg8000 driver
    # Note the +pg8000 in the string
    if "postgresql" in raw_uri:
        SQLALCHEMY_DATABASE_URL = raw_uri.replace("postgresql://", "postgresql+psycopg2://")
    else:
        SQLALCHEMY_DATABASE_URL = raw_uri
else:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()