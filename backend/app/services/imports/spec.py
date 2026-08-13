"""What a legacy import file must contain — declared once.

The downloadable template and the validator are generated from the same table below.
That is the whole point of this module: a sample that says one thing while the
importer expects another is worse than no sample at all, because the user trusts it
and only finds out after building a spreadsheet of ten thousand rows.

Column order here is the column order in the template, and `example` rows become the
filled-in demonstration rows the user can delete.
"""

from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["text", "decimal", "int", "date", "bool", "choice"]


@dataclass(frozen=True)
class Column:
    """One column, in both the template and the parser."""

    name: str  # exact header the file must carry
    label: str  # Arabic heading shown in the guide sheet
    kind: Kind
    required: bool = False
    choices: tuple[str, ...] = ()
    # Two demonstration values, becoming the template's two example rows.
    examples: tuple[str, str] = ("", "")
    note: str = ""  # Arabic guidance, shown in the guide sheet


@dataclass(frozen=True)
class Sheet:
    name: str  # sheet name in the workbook / CSV file name
    title: str
    purpose: str
    columns: tuple[Column, ...] = field(default_factory=tuple)


PRODUCTS = Sheet(
    name="products",
    title="الأصناف",
    purpose=(
        "بطاقة الصنف وأسعاره ووحداته. رمز الصنف (sku) هو المفتاح: إعادة الرفع "
        "تحدّث الصنف الموجود بنفس الرمز ولا تنشئ صنفاً مكرراً."
    ),
    columns=(
        Column("sku", "رمز الصنف", "text", required=True,
               examples=("P-1001", "P-1002"),
               note="مفتاح فريد. لو تكرر داخل الملف يُرفض الملف."),
        Column("name", "اسم الصنف", "text", required=True,
               examples=("أرز بسمتي 5 كجم", "زيت دوار الشمس 1 لتر")),
        Column("base_unit_name", "الوحدة الأساسية", "text", required=True,
               examples=("كيس", "عبوة"),
               note="أصغر وحدة تُباع بها. كل الكميات في كل الملفات بهذه الوحدة."),
        Column("barcode", "الباركود", "text",
               examples=("6281000012345", ""),
               note="اختياري، ولكن إن وُجد يجب ألا يتكرر بين صنفين."),
        Column("wholesale_price", "سعر الجملة", "decimal", required=True,
               examples=("10.50", "7.25")),
        Column("half_wholesale_price", "سعر نصف الجملة", "decimal", required=True,
               examples=("11.25", "7.80")),
        Column("retail_price", "سعر التجزئة", "decimal", required=True,
               examples=("12.00", "8.50")),
        Column("min_stock_level", "حد إعادة الطلب", "decimal",
               examples=("50", "100"),
               note="الكمية التي ينبّه النظام عند النزول إليها. اتركه فارغاً = صفر."),
        Column("warehouse", "المستودع الافتراضي", "text",
               examples=("المستودع الرئيسي", "المستودع الرئيسي"),
               note="اسم المستودع كما سيظهر في النظام. يُنشأ تلقائياً إن لم يكن موجوداً."),
        Column("unit1_name", "وحدة إضافية (1)", "text",
               examples=("كرتونة", ""),
               note="مثال: كرتونة. اتركه فارغاً إن لم توجد وحدة أكبر."),
        Column("unit1_factor", "معامل التحويل (1)", "decimal",
               examples=("12", ""),
               note="كم وحدة أساسية داخل الوحدة الإضافية. كرتونة = 12 كيس ⇐ اكتب 12."),
        Column("unit2_name", "وحدة إضافية (2)", "text", examples=("", "")),
        Column("unit2_factor", "معامل التحويل (2)", "decimal", examples=("", "")),
        Column("is_active", "مُفعّل", "bool",
               examples=("نعم", "نعم"),
               note="نعم / لا. الفارغ يعني نعم."),
    ),
)

OPENING_STOCK = Sheet(
    name="opening_stock",
    title="المخزون الافتتاحي",
    purpose=(
        "الكميات الموجودة فعلياً في المستودع اليوم، بتشغيلاتها وتواريخ صلاحيتها. "
        "هذه هي الحقيقة التي يبدأ منها النظام — وليست حركة شراء أو بيع. "
        "الفواتير التاريخية المستوردة لا تُنقص هذه الكميات."
    ),
    columns=(
        Column("sku", "رمز الصنف", "text", required=True,
               examples=("P-1001", "P-1002"),
               note="يجب أن يكون موجوداً في ورقة الأصناف."),
        Column("warehouse", "المستودع", "text", required=True,
               examples=("المستودع الرئيسي", "المستودع الرئيسي")),
        Column("batch_number", "رقم التشغيلة", "text", required=True,
               examples=("B-2026-01", "B-2026-04"),
               note="إلزامي لكل مادة غذائية. لو لا يوجد رقم لدى النظام القديم اكتب رقماً موحداً مثل OPENING."),
        Column("expiry_date", "تاريخ الانتهاء", "date", required=True,
               examples=("2027-03-31", "2026-12-15"),
               note="بصيغة YYYY-MM-DD. التشغيلة المنتهية لن تُباع (قاعدة FEFO)."),
        Column("quantity", "الكمية", "decimal", required=True,
               examples=("240", "600"),
               note="بالوحدة الأساسية للصنف، لا بالكرتونة."),
        Column("unit_cost", "تكلفة الوحدة", "decimal",
               examples=("8.20", "5.90"),
               note="تكلفة الشراء للوحدة الأساسية. مهمة لتقارير الربحية وقيمة المخزون."),
    ),
)

CUSTOMERS = Sheet(
    name="customers",
    title="العملاء",
    purpose=(
        "بطاقة العميل وحده الائتماني وفئة سعره. الاسم هو المفتاح: إعادة الرفع "
        "تحدّث العميل الموجود بنفس الاسم."
    ),
    columns=(
        Column("name", "اسم العميل", "text", required=True,
               examples=("سوبرماركت النخبة", "بقالة الأمانة")),
        Column("phone", "الهاتف", "text", examples=("0791234567", "0787654321")),
        Column("address", "العنوان", "text", examples=("عمّان — الصويفية", "إربد — وسط البلد")),
        Column("price_tier", "فئة السعر", "choice",
               choices=("wholesale", "half_wholesale", "retail"),
               examples=("wholesale", "retail"),
               note="wholesale = جملة، half_wholesale = نصف جملة، retail = تجزئة."),
        Column("credit_limit", "الحد الائتماني", "decimal",
               examples=("5000", "1500"),
               note="أقصى مديونية مسموحة. صفر = بيع نقدي فقط."),
        Column("opening_balance", "رصيد افتتاحي", "decimal",
               examples=("0", "0"),
               note=(
                   "الرصيد السابق لأقدم فاتورة مستوردة. اتركه صفراً إن كنت تستورد "
                   "كل الفواتير — وإلا حُسبت المديونية مرتين."
               )),
        Column("expected_balance", "الرصيد حسب النظام القديم", "decimal",
               examples=("1250.00", "0"),
               note=(
                   "للمطابقة فقط، لا يُحفظ. بعد الاستيراد يقارن النظام الرصيد الذي "
                   "حسبه بهذا الرقم ويعرض أي اختلاف. أهم عمود في الملف."
               )),
        Column("salesman_username", "اسم مستخدم المندوب", "text",
               examples=("salesman", ""),
               note="اسم المستخدم في النظام الجديد، وليس الاسم الكامل. يجب أن يكون موجوداً."),
        Column("is_active", "مُفعّل", "bool", examples=("نعم", "نعم")),
    ),
)

SALES_INVOICES = Sheet(
    name="sales_invoices",
    title="فواتير المبيعات — الرؤوس",
    purpose=(
        "رأس كل فاتورة. الأسطر في ورقة منفصلة مرتبطة برقم الفاتورة القديم. "
        "الفاتورة المستوردة تُرحّل محاسبياً (مدين ذمم / دائن مبيعات وضريبة) "
        "ولكنها لا تُحرّك المخزون، لأن المخزون الحالي مأخوذ من ورقة المخزون الافتتاحي."
    ),
    columns=(
        Column("invoice_ref", "رقم الفاتورة القديم", "text", required=True,
               examples=("INV-2026-0001", "INV-2026-0002"),
               note="مفتاح الربط مع الأسطر، ويمنع تكرار الاستيراد عند إعادة الرفع."),
        Column("customer_name", "اسم العميل", "text", required=True,
               examples=("سوبرماركت النخبة", "بقالة الأمانة"),
               note="يجب أن يطابق اسماً في ورقة العملاء أو عميلاً موجوداً."),
        Column("invoice_date", "تاريخ الفاتورة", "date", required=True,
               examples=("2026-02-11", "2026-03-04")),
        Column("payment_method", "طريقة الدفع", "choice", required=True,
               choices=("cash", "card", "credit"),
               examples=("credit", "cash"),
               note="cash = نقدي، card = بطاقة، credit = آجل."),
        Column("subtotal", "المجموع قبل الضريبة", "decimal", required=True,
               examples=("262.50", "84.00"),
               note="يجب أن يساوي مجموع أسطر الفاتورة، وإلا رُفض الملف."),
        Column("discount_amount", "الخصم", "decimal",
               examples=("0", "4.00")),
        Column("tax_amount", "قيمة الضريبة", "decimal",
               examples=("42.00", "12.80")),
        Column("tax_name", "اسم الضريبة", "text",
               examples=("ضريبة المبيعات", "ضريبة المبيعات")),
        Column("tax_rate", "نسبة الضريبة %", "decimal",
               examples=("16", "16")),
        Column("total", "الإجمالي", "decimal", required=True,
               examples=("304.50", "92.80"),
               note="يجب أن يساوي (المجموع − الخصم + الضريبة)، وإلا رُفض الملف."),
        Column("paid_amount", "المدفوع من الفاتورة", "decimal",
               examples=("304.50", "0"),
               note="ما سُدّد على هذه الفاتورة تحديداً. لا يمكن أن يتجاوز الإجمالي."),
        Column("salesman_username", "اسم مستخدم المندوب", "text",
               examples=("salesman", "")),
        Column("warehouse", "المستودع", "text",
               examples=("المستودع الرئيسي", "المستودع الرئيسي")),
        Column("notes", "ملاحظات", "text", examples=("", "")),
    ),
)

SALES_INVOICE_LINES = Sheet(
    name="sales_invoice_lines",
    title="فواتير المبيعات — الأسطر",
    purpose=(
        "أسطر الفواتير. كل سطر يشير إلى فاتورة برقمها القديم وإلى صنف برمزه. "
        "تكلفة الوحدة تغذّي تقارير هامش الربح التاريخية، فاحرص على تعبئتها."
    ),
    columns=(
        Column("invoice_ref", "رقم الفاتورة القديم", "text", required=True,
               examples=("INV-2026-0001", "INV-2026-0001"),
               note="يجب أن يوجد في ورقة رؤوس الفواتير."),
        Column("sku", "رمز الصنف", "text", required=True,
               examples=("P-1001", "P-1002")),
        Column("quantity", "الكمية", "decimal", required=True,
               examples=("20", "5"),
               note="بالوحدة الأساسية."),
        Column("unit_price", "سعر البيع للوحدة", "decimal", required=True,
               examples=("10.50", "10.50")),
        Column("unit_cost", "تكلفة الوحدة", "decimal",
               examples=("8.20", "8.20"),
               note="تكلفة البضاعة المباعة. بدونها تظهر أرباح التقارير التاريخية مبالغاً فيها."),
        Column("batch_number", "رقم التشغيلة", "text",
               examples=("B-2026-01", ""),
               note=(
                   "اختياري. التشغيلة المذكورة هنا للتوثيق فقط ولا تُخصم كميتها. "
                   "إن تُركت فارغة يُربط السطر بتشغيلة أرشيفية باسم LEGACY."
               )),
    ),
)

CUSTOMER_PAYMENTS = Sheet(
    name="customer_payments",
    title="سندات القبض",
    purpose=(
        "المبالغ المحصّلة من العملاء. تُرحّل محاسبياً (مدين صندوق أو بنك / دائن ذمم) "
        "وتدخل في كشف الحساب."
    ),
    columns=(
        Column("payment_ref", "رقم السند القديم", "text", required=True,
               examples=("RC-2026-0001", "RC-2026-0002"),
               note="يمنع تكرار الاستيراد عند إعادة الرفع."),
        Column("customer_name", "اسم العميل", "text", required=True,
               examples=("سوبرماركت النخبة", "بقالة الأمانة")),
        Column("payment_date", "تاريخ السند", "date", required=True,
               examples=("2026-02-20", "2026-03-10")),
        Column("amount", "المبلغ", "decimal", required=True,
               examples=("150.00", "92.80"),
               note="أكبر من صفر."),
        Column("method", "طريقة القبض", "choice", required=True,
               choices=("cash", "bank", "card"),
               examples=("cash", "bank"),
               note="cash = صندوق، bank = بنك، card = بطاقة."),
        Column("reference", "مرجع", "text", examples=("شيك 4412", "")),
        Column("notes", "ملاحظات", "text", examples=("", "")),
    ),
)

SUPPLIERS = Sheet(
    name="suppliers",
    title="الموردون",
    purpose=(
        "بطاقة المورد ورصيده. الاسم هو المفتاح: إعادة الرفع تحدّث المورد الموجود "
        "بنفس الاسم ولا تنشئ مورداً مكرراً."
    ),
    columns=(
        Column("name", "اسم المورد", "text", required=True,
               examples=("شركة الغذاء الوطنية", "مؤسسة البركة للتوريد"),
               note="مفتاح فريد. لو تكرر داخل الملف يُرفض الملف."),
        Column("phone", "الهاتف", "text", examples=("0551234567", "")),
        Column("address", "العنوان", "text", examples=("الرياض", "")),
        Column("opening_balance", "رصيد افتتاحي (مستحق للمورد)", "decimal",
               examples=("0", "0"),
               note=(
                   "ما كان مستحقاً للمورد قبل أول فاتورة تستوردها. "
                   "إن استوردت كل فواتيره فاتركه صفراً، وإلا حُسب الدين مرتين."
               )),
        Column("lead_time_days", "مهلة التوريد (يوم)", "int",
               examples=("7", "14"),
               note="عدد الأيام المعتادة بين الطلب والاستلام. يُستخدم في نقطة إعادة الطلب."),
        Column("is_active", "مُفعّل", "bool", examples=("نعم", "نعم")),
        Column("legacy_balance", "الرصيد حسب النظام القديم", "decimal",
               examples=("", ""),
               note=(
                   "اختياري لكنه مُوصى به بشدة: بعد الاستيراد يُقارن بما حسبه النظام "
                   "ويُعرض أي اختلاف في جدول المطابقة."
               )),
    ),
)

PURCHASE_INVOICES = Sheet(
    name="purchase_invoices",
    title="فواتير المشتريات — الرؤوس",
    purpose=(
        "رأس كل فاتورة شراء. تُرحّل محاسبياً (مدين تكلفة البضاعة والضريبة / دائن ذمم "
        "الموردين) ولكنها **لا تزيد المخزون**، لأن المخزون الحالي مأخوذ من ورقة "
        "المخزون الافتتاحي — ولو زادته الفواتير التاريخية أيضاً لتضاعف."
    ),
    columns=(
        Column("invoice_ref", "رقم الفاتورة القديم", "text", required=True,
               examples=("PINV-2026-0001", "PINV-2026-0002"),
               note="مفتاح الربط مع الأسطر، ويمنع تكرار الاستيراد عند إعادة الرفع."),
        Column("supplier_name", "اسم المورد", "text", required=True,
               examples=("شركة الغذاء الوطنية", "مؤسسة البركة للتوريد"),
               note="يجب أن يطابق اسماً في ورقة الموردين أو مورداً موجوداً."),
        Column("invoice_date", "تاريخ الفاتورة", "date", required=True,
               examples=("2026-01-15", "2026-02-02")),
        Column("payment_method", "طريقة الدفع", "choice", required=True,
               choices=("cash", "card", "credit"),
               examples=("credit", "cash"),
               note="cash = نقدي، card = بطاقة، credit = آجل."),
        Column("supplier_invoice_number", "رقم فاتورة المورد", "text",
               examples=("SUP-9911", "")),
        Column("subtotal", "المجموع قبل الضريبة", "decimal", required=True,
               examples=("1640.00", "820.00"),
               note="يجب أن يساوي مجموع أسطر الفاتورة، وإلا رُفض الملف."),
        Column("shipping_cost", "الشحن", "decimal",
               examples=("0", "25.00"),
               note="يُضاف إلى التكلفة ويدخل في الإجمالي."),
        Column("tax_amount", "قيمة الضريبة", "decimal",
               examples=("262.40", "135.20")),
        Column("total", "الإجمالي", "decimal", required=True,
               examples=("1902.40", "980.20"),
               note="يجب أن يساوي (المجموع + الشحن + الضريبة)، وإلا رُفض الملف."),
        Column("paid_amount", "المدفوع من الفاتورة", "decimal",
               examples=("0", "980.20"),
               note="ما سُدّد على هذه الفاتورة تحديداً. لا يمكن أن يتجاوز الإجمالي."),
        Column("warehouse", "المستودع", "text",
               examples=("المستودع الرئيسي", "المستودع الرئيسي")),
        Column("notes", "ملاحظات", "text", examples=("", "")),
    ),
)

PURCHASE_INVOICE_LINES = Sheet(
    name="purchase_invoice_lines",
    title="فواتير المشتريات — الأسطر",
    purpose=(
        "أسطر فواتير الشراء. تُوثّق ما شُتري وبأي تكلفة، ولا تُضاف كميتها إلى المخزون."
    ),
    columns=(
        Column("invoice_ref", "رقم الفاتورة القديم", "text", required=True,
               examples=("PINV-2026-0001", "PINV-2026-0001"),
               note="يجب أن يوجد في ورقة رؤوس فواتير الشراء."),
        Column("sku", "رمز الصنف", "text", required=True,
               examples=("P-1001", "P-1002")),
        Column("quantity", "الكمية", "decimal", required=True,
               examples=("200", "100"),
               note="بالوحدة الأساسية. للتوثيق فقط — لا تُضاف إلى الرصيد."),
        Column("unit_cost", "تكلفة الوحدة", "decimal", required=True,
               examples=("8.20", "0"),
               note="تكلفة الشراء الفعلية للوحدة."),
        Column("batch_number", "رقم التشغيلة", "text",
               examples=("B-2026-01", ""),
               note=(
                   "اختياري وللتوثيق فقط. إن تُركت فارغة يُربط السطر بتشغيلة "
                   "أرشيفية باسم LEGACY كميتها صفر."
               )),
        Column("expiry_date", "تاريخ الانتهاء", "date",
               examples=("2026-12-31", ""),
               note="اختياري. للتوثيق التاريخي فقط."),
    ),
)

SUPPLIER_PAYMENTS = Sheet(
    name="supplier_payments",
    title="سندات الصرف للموردين",
    purpose=(
        "المبالغ المدفوعة للموردين. تُرحّل محاسبياً (مدين ذمم الموردين / دائن صندوق "
        "أو بنك) وتُخفّض المستحق عليهم."
    ),
    columns=(
        Column("payment_ref", "رقم السند القديم", "text", required=True,
               examples=("PV-2026-0001", "PV-2026-0002"),
               note="يمنع تكرار الاستيراد عند إعادة الرفع."),
        Column("supplier_name", "اسم المورد", "text", required=True,
               examples=("شركة الغذاء الوطنية", "مؤسسة البركة للتوريد")),
        Column("payment_date", "تاريخ السند", "date", required=True,
               examples=("2026-01-30", "2026-02-15")),
        Column("amount", "المبلغ", "decimal", required=True,
               examples=("900.00", "980.20"),
               note="أكبر من صفر."),
        Column("method", "طريقة الصرف", "choice", required=True,
               choices=("cash", "bank", "card"),
               examples=("bank", "cash"),
               note="cash = صندوق، bank = بنك، card = بطاقة."),
        Column("reference", "مرجع", "text", examples=("حوالة 8821", "")),
        Column("notes", "ملاحظات", "text", examples=("", "")),
    ),
)


# Order matters: it is the order the importer processes them, and each depends only
# on those before it. Products before stock, customers before invoices, invoice
# headers before their lines.
SHEETS: tuple[Sheet, ...] = (
    PRODUCTS,
    OPENING_STOCK,
    CUSTOMERS,
    SALES_INVOICES,
    SALES_INVOICE_LINES,
    CUSTOMER_PAYMENTS,
    SUPPLIERS,
    PURCHASE_INVOICES,
    PURCHASE_INVOICE_LINES,
    SUPPLIER_PAYMENTS,
)

SHEETS_BY_NAME: dict[str, Sheet] = {sheet.name: sheet for sheet in SHEETS}

# Shown at the top of the guide sheet. The two rules people get wrong.
GUIDE_RULES: tuple[str, ...] = (
    "الاستيراد إمّا أن ينجح كاملاً أو يُرفض كاملاً. لا يُحفظ أي سطر إذا كان في الملف خطأ واحد.",
    "ارفع الملف أولاً بوضع «فحص فقط» لمراجعة الأخطاء قبل التنفيذ.",
    "كل الكميات بالوحدة الأساسية للصنف (لا بالكرتونة).",
    "كل التواريخ بصيغة YYYY-MM-DD، مثال 2026-03-31.",
    "الأرقام بدون فواصل آلاف وبنقطة عشرية، مثال 1234.50 وليس 1,234.50.",
    (
        "المخزون الحالي يأتي من ورقة «المخزون الافتتاحي» فقط: فواتير المبيعات "
        "التاريخية لا تُنقصه، وفواتير المشتريات التاريخية لا تزيده. لو فعلت الاثنتان "
        "لتضاعف المخزون — الكمية الموجودة على الرف مُدخلة مرة واحدة بالفعل."
    ),
    (
        "فواتير المشتريات التاريخية تُرحَّل كتكلفة بضاعة مباعة لا كأصل مخزني، "
        "والمخزون الافتتاحي هو ما يُثبت الأصل مقابل رأس المال. هذه طريقة الجرد "
        "الدوري، وهي الوحيدة الصحيحة عند استيراد تاريخ جزئي."
    ),
    (
        "إذا استوردت كل فواتير العميل فاترك «رصيد افتتاحي» صفراً، "
        "وإلا حُسبت مديونيته مرتين. والقاعدة نفسها تنطبق على الموردين."
    ),
    "لا يمكن تكرار استيراد نفس رقم الفاتورة أو نفس رقم السند مرتين — بيعاً أو شراءً.",
    (
        "المبلغ المحصّل يُسجَّل في مكان واحد فقط: إمّا في «المدفوع من الفاتورة» "
        "إن سُدّد عند البيع، أو في ورقة سندات القبض إن حُصّل لاحقاً — لا في الاثنين."
    ),
    (
        "عمود «الرصيد حسب النظام القديم» هو ضمانتك: بعد الاستيراد يعرض النظام "
        "جدول مطابقة يكشف أي عميل اختلف رصيده، وهو ما يكشف الأخطاء الصامتة."
    ),
)
