"""When to reorder, and how much — with the reasoning attached.

Pure arithmetic over a `Demand` and the company's replenishment settings, kept
apart from the queries so it can be read, argued with and tested on its own.

Two ideas, both chosen to be explainable to a warehouse manager rather than to a
statistician.

**The reorder point is days of cover, not a z-score.** Stock should be reordered
when what is left will just carry the business through the supplier's lead time plus
a buffer. Someone can disagree with "seven days of cover"; nobody can disagree with
`z=1.65` because nobody knows what it means. With demand as intermittent as this —
439 of 1,060 products sold on three days or fewer in a year — a normal-curve safety
stock would be false precision anyway.

**The order is capped by the expiry date.** This is the part a generic ERP gets
wrong. The economic order quantity says buy more to save on ordering cost; the
yoghurt says otherwise. Never order more than will sell before it perishes.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.services.inventory.demand_service import Demand, DemandConfidence, rounded_units

ZERO = Decimal("0")


@dataclass(frozen=True)
class ReplenishmentSettings:
    lead_time_days: int
    safety_stock_days: int
    review_days: int


@dataclass(frozen=True)
class Reorder:
    """What to do about one product, and why."""

    reorder_point: Decimal
    suggested_quantity: Decimal
    # True when the point came from measured demand; False when it is the
    # hand-entered `min_stock_level` standing in.
    computed: bool
    # Arabic sentence explaining the number, shown next to it on the screen. A
    # suggestion a buyer cannot interrogate is a suggestion they will ignore.
    basis: str
    # Set when the order was trimmed to what will sell before it expires.
    capped_by_expiry: bool = False


def reorder_for(
    demand: Demand,
    current_stock: Decimal,
    min_stock_level: Decimal,
    settings: ReplenishmentSettings,
) -> Reorder:
    """The reorder point and order quantity for one product."""
    lead = demand.lead_time_days
    cover_days = lead + settings.safety_stock_days

    if demand.confidence is not DemandConfidence.MEASURED:
        # Not enough history to compute anything honest, so the human's number
        # stands. Deliberately not "zero demand, therefore reorder point zero":
        # a product that sold three times still sells, and quietly setting its
        # threshold to nothing is how it silently disappears from the catalogue.
        reason = (
            "لا توجد مبيعات خلال السنة الأخيرة"
            if demand.confidence is DemandConfidence.NONE
            else f"بيع في {demand.sale_days} أيام فقط خلال السنة — تاريخ غير كافٍ للحساب"
        )
        return Reorder(
            reorder_point=min_stock_level,
            suggested_quantity=max(min_stock_level - current_stock, ZERO),
            computed=False,
            basis=f"{reason}؛ الحد المُدخل يدوياً هو المستخدم.",
        )

    rate = demand.daily_rate
    reorder_point = rounded_units(rate * Decimal(cover_days))

    # The order must last until the *next* order is placed, not merely until this
    # one lands — otherwise every review period reorders the same shortfall again.
    target = rounded_units(rate * Decimal(cover_days + settings.review_days))
    quantity = max(target - current_stock, ZERO)

    capped = False
    if demand.shelf_life_days:
        sellable_before_expiry = rounded_units(rate * Decimal(demand.shelf_life_days))
        if quantity > sellable_before_expiry:
            quantity = sellable_before_expiry
            capped = True

    supplier = f" ({demand.supplier_name})" if demand.supplier_name else ""
    basis = (
        f"يبيع {rate} يومياً · التوريد {lead} يوم{supplier} · "
        f"احتياطي {settings.safety_stock_days} يوم ⇐ نقطة الطلب {reorder_point}"
    )
    if capped:
        basis += (
            f" · الكمية محدودة بما يُباع قبل انتهاء الصلاحية "
            f"({demand.shelf_life_days} يوم)"
        )

    return Reorder(
        reorder_point=reorder_point,
        suggested_quantity=quantity,
        computed=True,
        basis=basis,
        capped_by_expiry=capped,
    )
