"""Delivery entities: distribution trips and their invoice stops."""

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TripStatus(str, enum.Enum):
    PLANNED = "planned"  # مخططة — يجري تجهيزها
    IN_TRANSIT = "in_transit"  # قيد التوصيل
    COMPLETED = "completed"  # مكتملة


class StopStatus(str, enum.Enum):
    PENDING = "pending"  # بانتظار التسليم
    DELIVERED = "delivered"  # تم التسليم
    FAILED = "failed"  # تعذر التسليم


class DeliveryTrip(Base):
    __tablename__ = "delivery_trips"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trip_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    driver_name: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle: Mapped[str | None] = mapped_column(String(100))
    # Goods are picked and loaded from this warehouse.
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id"), nullable=False
    )
    status: Mapped[TripStatus] = mapped_column(
        Enum(TripStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TripStatus.PLANNED,
    )
    notes: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    stops: Mapped[list["DeliveryStop"]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        order_by="DeliveryStop.sequence",
    )


class DeliveryStop(Base):
    """One customer stop on a trip, backed by a posted sales invoice."""

    __tablename__ = "delivery_stops"
    __table_args__ = (
        UniqueConstraint("trip_id", "invoice_id", name="uq_invoice_once_per_trip"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trip_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_trips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("sales_invoices.id"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[StopStatus] = mapped_column(
        Enum(StopStatus, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=StopStatus.PENDING,
    )
    notes: Mapped[str | None] = mapped_column(String(300))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    trip: Mapped[DeliveryTrip] = relationship(back_populates="stops")
