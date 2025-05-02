from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.ext.declarative import declarative_base
from alembic import context

# Define our own Base for migrations
Base = declarative_base()

# This is a simplified approach where we define the tables directly for migrations
# without importing the models, to avoid circular import issues
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

class RingEvent(Base):
    """SQLAlchemy model for Ring events."""
    
    __tablename__ = "ring_events"
    
    # Primary key and basic identification
    id = Column(String(50), primary_key=True, index=True)
    
    # Event metadata
    kind = Column(String(20), nullable=False, index=True)  # ding, motion, on_demand
    created_at = Column(String(50), nullable=False, index=True)  # ISO format timestamp
    
    # Device information
    device_id = Column(String(50), nullable=False, index=True)
    device_name = Column(String(100), nullable=False)
    
    # Event specific data stored as JSON
    event_data = Column(Text, nullable=False)
    
    # Tracking fields
    stored_at = Column(DateTime, server_default=func.now())

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()