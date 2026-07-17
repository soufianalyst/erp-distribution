"""Granular permission catalog and per-user resolution.

Roles act as default permission templates; a user with an explicit `permissions`
list overrides their role's defaults entirely. Admins always hold every
permission so the system can never be locked out.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models.user import User

# --- Catalog: (code, Arabic label), grouped for the management UI ---
PERMISSION_GROUPS: list[dict] = [
    {
        "group": "المخزون",
        "permissions": [
            {"code": "products.view", "label": "عرض الأصناف"},
            {"code": "products.manage", "label": "إدارة الأصناف والأسعار"},
            {"code": "warehouses.view", "label": "عرض المستودعات"},
            {"code": "warehouses.manage", "label": "إدارة المستودعات"},
            {"code": "stock.view", "label": "عرض الأرصدة وتقارير الصلاحية"},
            {"code": "stock.receive", "label": "استلام بضاعة"},
            {"code": "stock.transfer", "label": "التحويل بين المستودعات"},
        ],
    },
    {
        "group": "المبيعات",
        "permissions": [
            {"code": "customers.view", "label": "عرض العملاء"},
            {"code": "customers.manage", "label": "إدارة العملاء والحدود الائتمانية"},
            {"code": "sales.view", "label": "عرض فواتير المبيعات"},
            {"code": "sales.create", "label": "إصدار فواتير مبيعات"},
            {"code": "sales.edit", "label": "تعديل فواتير المبيعات"},
            {"code": "sales.delete", "label": "حذف فواتير المبيعات"},
            {"code": "sales.returns", "label": "تسجيل مرتجعات المبيعات"},
            {"code": "sales.payments", "label": "سندات قبض من العملاء"},
            {
                "code": "sales.all_customers",
                "label": "الوصول لجميع العملاء (وليس عملاءه فقط)",
            },
            {
                "code": "sales.credit_override",
                "label": "الموافقة على تجاوز الحد الائتماني",
            },
        ],
    },
    {
        "group": "المشتريات",
        "permissions": [
            {"code": "suppliers.view", "label": "عرض الموردين"},
            {"code": "suppliers.manage", "label": "إدارة الموردين وكشوف حساباتهم"},
            {"code": "purchases.view", "label": "عرض فواتير المشتريات"},
            {"code": "purchases.create", "label": "تثبيت فواتير شراء"},
            {"code": "purchases.payments", "label": "سندات صرف للموردين"},
        ],
    },
    {
        "group": "التوزيع والتسليم",
        "permissions": [
            {"code": "delivery.view", "label": "متابعة رحلات التوزيع وقوائم التجهيز"},
            {"code": "delivery.manage", "label": "إدارة الرحلات والتسليم"},
            {
                "code": "delivery.deliver",
                "label": "تسليم الطلبيات وتحديث حالتها أثناء الرحلة",
            },
        ],
    },
    {
        "group": "الحسابات",
        "permissions": [
            {"code": "accounting.view", "label": "عرض القيود وميزان المراجعة"},
            {
                "code": "accounting.manual_entry",
                "label": "تسجيل قيود يدوية وإدارة الحسابات",
            },
        ],
    },
    {
        "group": "النظام",
        "permissions": [
            {"code": "users.manage", "label": "إدارة المستخدمين والصلاحيات"},
        ],
    },
    {
        "group": "التحليلات",
        "permissions": [
            {"code": "analytics.view", "label": "عرض لوحة التحليلات والتقارير"},
        ],
    },
]

ALL_PERMISSIONS: frozenset[str] = frozenset(
    item["code"] for group in PERMISSION_GROUPS for item in group["permissions"]
)

# Role templates, applied when a user has no explicit permission list.
ROLE_DEFAULT_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": ALL_PERMISSIONS,
    "storekeeper": frozenset(
        {
            "products.view",
            "warehouses.view",
            "stock.view",
            "stock.receive",
            "stock.transfer",
            "delivery.view",
            "delivery.manage",
            "delivery.deliver",
        }
    ),
    "sales": frozenset(
        {
            "products.view",
            "warehouses.view",
            "stock.view",
            "customers.view",
            "sales.view",
            "sales.create",
            "sales.returns",
            "sales.payments",
            "delivery.view",
        }
    ),
    "driver": frozenset(
        {
            "warehouses.view",
            "delivery.view",
            "delivery.deliver",
        }
    ),
    "accountant": frozenset(
        {
            "products.view",
            "warehouses.view",
            "stock.view",
            "customers.view",
            "customers.manage",
            "sales.view",
            "sales.payments",
            "sales.all_customers",
            "suppliers.view",
            "suppliers.manage",
            "purchases.view",
            "purchases.create",
            "purchases.payments",
            "accounting.view",
            "accounting.manual_entry",
            "analytics.view",
        }
    ),
}


def effective_permissions(user: "User") -> set[str]:
    """Resolve a user's actual permissions: admin = all; explicit list wins; else role defaults."""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role == "admin":
        return set(ALL_PERMISSIONS)
    if user.permissions is not None:
        return set(user.permissions) & ALL_PERMISSIONS
    return set(ROLE_DEFAULT_PERMISSIONS.get(role, frozenset()))


def has_permission(user: "User", permission: str) -> bool:
    return permission in effective_permissions(user)
