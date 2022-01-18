import json
import uuid

from sqlalchemy import (
    Binary,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Table,
    Unicode,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import Text, TypeDecorator

from .database import Base
from .models import PrincipalType


class JSONList(TypeDecorator):
    """Represents an immutable structure as a JSON-encoded list.

    Usage::

        JSONList(255)

    """

    impl = Text

    def process_bind_param(self, value, dialect):
        # Make sure we don't get passed some iterable like a dict.
        if not isinstance(value, list):
            raise ValueError("JSONList must be given a literal `list` type.")
        if value is not None:
            value = json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = json.loads(value)
        return value


class Timestamped:
    """
    Mixin for providing timestamps of creation and update time.

    These are not used by application code, but they may be useful for
    forensics.
    """

    time_created = Column(DateTime(timezone=True), server_default=func.now())
    time_updated = Column(
        DateTime(timezone=True), onupdate=func.now()
    )  # null until first update

    def __repr__(self):
        return (
            f"{type(self).__name__}("
            + ", ".join(
                f"{key}={value!r}"
                for key, value in self.__dict__.items()
                if not key.startswith("_")
            )
            + ")"
        )


principal_role_association_table = Table(
    "principal_role_association",
    Base.metadata,
    Column("principal_id", Integer, ForeignKey("principals.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
)


class Principal(Timestamped, Base):
    __tablename__ = "principals"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    type = Column(Enum(PrincipalType), nullable=False)
    display_name = Column(Unicode(255), nullable=False)
    # In the future we may add other information.

    identities = relationship("Identity", back_populates="principal")
    api_keys = relationship("APIKey", back_populates="principal")
    roles = relationship(
        "Role", secondary=principal_role_association_table, back_populates="principals"
    )
    sessions = relationship("Session", back_populates="principal")


class Identity(Timestamped, Base):
    __tablename__ = "identities"

    # An (external_id, provider) pair must be unique.
    external_id = Column(Unicode(255), primary_key=True, nullable=False)
    provider = Column(Unicode(255), primary_key=True, nullable=False)
    principal_id = Column(Integer, ForeignKey("principals.id"), nullable=False)
    # In the future we may add a notion of "primary" identity.

    principal = relationship("Principal", back_populates="identities")


class Role(Timestamped, Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    scopes = Column(JSONList, nullable=False)
    principals = relationship(
        "Principal", secondary=principal_role_association_table, back_populates="roles"
    )


class APIKey(Timestamped, Base):
    __tablename__ = "api_keys"

    hashed_api_key = Column(Unicode(255), primary_key=True, index=True, nullable=False)
    expiration_time = Column(DateTime(timezone=True), nullable=True)
    note = Column(Unicode(1023), nullable=True)
    principal_id = Column(Integer, ForeignKey("principals.id"), nullable=False)
    scopes = Column(JSONList, nullable=False)
    # In the future we could make it possible to disable API keys
    # without deleting them from the database, for forensics and
    # record-keeping.

    principal = relationship("Principal", back_populates="api_keys")


class Session(Timestamped, Base):
    """
    This related to refresh tokens, which have a session_id.

    When the client attempts to use a refresh token, we first check
    here to ensure that the "session", which is associated with a chain
    of refresh tokens that came from a single authentication, are still valid.
    """

    __tablename__ = "sessions"

    # SQLite does not support UUID4 type, so we use generic binary.
    id = Column(
        Binary(16),
        primary_key=True,
        index=True,
        nullable=False,
        default=lambda: uuid.uuid4().bytes,
    )
    expiration_time = Column(DateTime(timezone=True), nullable=False)
    principal_id = Column(Integer, ForeignKey("principals.id"), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)

    principal = relationship("Principal", back_populates="sessions")
