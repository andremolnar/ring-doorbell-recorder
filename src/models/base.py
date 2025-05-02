"""Base class for SQLAlchemy models."""

from sqlalchemy.ext.declarative import declarative_base

# Create the declarative base that all models will inherit from
Base = declarative_base()
