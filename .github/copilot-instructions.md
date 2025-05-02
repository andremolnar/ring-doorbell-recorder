# Ring Doorbell GitHub Copilot Configuration

## COMMIT MESSAGE FORMAT

Format commit messages as:

```
[scope]: Brief description of changes

- Detailed bullet points about what changed
- Another detail point if needed

Relates to: #migration-number (if applicable)
```

Where `scope` should be one of:

- `feature`: For feature updates
- `deps`: For dependency updates
- `docs`: For documentation updates
- `infra`: For infrastructure or build changes

## README instructions

When suggesting README updates:

- Keep the main project description concise and clear
- Include clear installation instructions
- Update environment configuration documentation
- Include troubleshooting section for common issues

The README should cover:

1. Project overview and purpose
2. Installation and setup instructions
3. Usage examples for both backend and frontend
4. API documentation
5. Contributing guidelines
6. License information

## CHANGELOG

When updating the changelog:

- Group changes under semantic versioning headers (e.g., ## 1.2.0)
- Use the following categories:
  - **Added**: For new features
  - **Changed**: For changes in existing functionality
  - **Deprecated**: For soon-to-be removed features
  - **Removed**: For removed features
  - **Fixed**: For bug fixes
  - **Security**: For security updates
- Include the date of the version release
- Reference relevant issue or PR numbers
- Highlight breaking changes prominently

## Patterns

patterns:

- name: "FastAPI Endpoints"
  description: "Follow the established pattern for FastAPI endpoints with proper typing, dependency injection, and error handling."
  example: |
  @router.get("/venues/{venue_id}", response_model=VenueResponse)
  async def get_venue(venue_id: int, db: Session = Depends(get_db)):
  """Get details for a specific venue."""
  venue = db.query(Venue).filter(Venue.id == venue_id).first()
  if venue is None:
  raise HTTPException(status_code=404, detail="Venue not found")
  return venue

- name: "SQLAlchemy Models"
  description: "Follow the established pattern for SQLAlchemy models with proper types and relationships."
  example: |
  class Venue(Base):
  **tablename** = "venues"
  id = Column(Integer, primary_key=True, index=True)
  name = Column(String(100), nullable=False) # Additional fields...
  address_id = Column(Integer, ForeignKey("addresses.id"), nullable=False)
  address = relationship("Address", back_populates="venues")

## Pydantic Models

description: "Structure Pydantic models with proper validation and clear separation between base, create, and response models."
example: |
class VenueBase(BaseModel):
name: str
contact_email: EmailStr = None
description: str = None

    class VenueCreate(VenueBase):
        address: AddressCreate

    class VenueResponse(VenueBase):
        id: int
        address: AddressResponse

        class Config:
            orm_mode = True


## Dependency injection
This is a strong perference for constructor dependency injection over function dependency injection

## Observer event bus
Use the Pyee library to implement an observer event bus pattern for decoupling components and handling events asynchronously.

## Data storage
- There is a preference for a small `IStorage` abstract-base class
- Each concrete storage focuses only on its own concerns (DB connection pooling, file I/O, network retry logic etc.)
- Use fsspec for file system abstraction and storage management.
- Use SQLAlchemy for database interactions.

## Preferred coding style

style:

- "Follow PEP 8 code style guidelines"
- "Follow PEP 484 and use Python type hints consistently throughout the codebase"
- "Follow PEP 257 to write descriptive docstrings for all functions and classes"
- "Use async/await patterns for FastAPI endpoints"
- "Use dependency injection for database sessions"

## Testing guidance

framework: pytest
patterns:

- "Write thorough unit tests for models"
- "Create integration tests for API endpoints"
- "Use test fixtures for database setup and teardown"

## Database schema updates

When making schema changes use alembic to generate versioned changes to the database

## Conda environemnt

This project is in a conda environment called ringdoorbell
prefix all python related command line actions with `conda activate ringdoorbell` to ensure they run in the proper environment

# Files to ignore

ignore:

- "**pycache**/"
- "\*.pyc"
- "ringdoorbell.db"
- ".env"
- "migrations/versions/\*" # Ignore specific migration content but not structure
