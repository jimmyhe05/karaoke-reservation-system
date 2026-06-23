from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Text
from sqlalchemy.orm import declarative_base, relationship
import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String)
    name = Column(String, nullable=False)
    google_id = Column(String, unique=True)
    email_notifications = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    reservations = relationship("Reservation", back_populates="user")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False)
    hourly_rate = Column(Float, nullable=False, default=35.0)
    peak_hour_rate = Column(Float, nullable=False, default=50.0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    reservations = relationship("Reservation", back_populates="room")


class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    date = Column(String, nullable=False)
    start_time = Column(String, nullable=False)
    end_time = Column(String, nullable=False)
    contact_name = Column(String, nullable=False)
    contact_phone = Column(String, nullable=False)
    contact_email = Column(String)
    num_people = Column(Integer, nullable=False)
    language = Column(String, default="en")
    status = Column(String, default="confirmed")
    total_cost = Column(Float, nullable=False)
    deposit_paid = Column(Float, default=0.0)
    cancellation_token = Column(String, unique=True, default=None)
    requested_at = Column(DateTime, default=None)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    room = relationship("Room", back_populates="reservations")
    user = relationship("User", back_populates="reservations")
    idle_reservations = relationship("IdleReservation", back_populates="reservation", cascade="all, delete-orphan")
    history = relationship("ReservationHistory", back_populates="reservation", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="reservation")


class IdleReservation(Base):
    __tablename__ = "idle_reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=False)
    date = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    reservation = relationship("Reservation", back_populates="idle_reservations")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String, nullable=False)
    role = Column(String, nullable=False)
    path = Column(String)
    method = Column(String)
    request_id = Column(String)
    details = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ReservationHistory(Base):
    __tablename__ = "reservation_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=False)
    action = Column(String, nullable=False)
    snapshot = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    reservation = relationship("Reservation", back_populates="history")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reservation_id = Column(Integer, ForeignKey("reservations.id", ondelete="SET NULL"))
    message = Column(Text, nullable=False)
    read = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="notifications")
    reservation = relationship("Reservation", back_populates="notifications")


class DirectMessage(Base):
    __tablename__ = "direct_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    session_id = Column(String, nullable=False)
    guest_name = Column(String)
    guest_email = Column(String)
    message = Column(String, nullable=False)
    sender_role = Column(String, nullable=False)
    read_by_staff = Column(Integer, default=0)
    read_by_user = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    user = relationship("User")
