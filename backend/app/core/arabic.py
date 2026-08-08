"""Arabic text helpers for user-facing messages.

Arabic agrees its nouns with number in a way that has no English equivalent:
one takes the singular, two takes a dual form, three to ten take the plural, and
eleven upwards returns to the singular. So "3 فاتورة" is wrong in exactly the way
"3 invoice" is wrong — and to the storekeepers and cashiers reading these messages
all day, that kind of slip reads as broken software.

Kept here rather than inline because the same counts appear in service messages
and in dashboard alerts, and three copies of the rule would eventually be three
different rules.
"""


def counted(count: int, singular: str, dual: str, plural: str) -> str:
    """Renders `count` with the right form of its noun.

    >>> counted(1, "فاتورة", "فاتورتان", "فواتير")
    'فاتورة واحدة'
    >>> counted(3, "فاتورة", "فاتورتان", "فواتير")
    '3 فواتير'
    >>> counted(15, "فاتورة", "فاتورتان", "فواتير")
    '15 فاتورة'
    """
    if count == 1:
        return f"{singular} واحدة"
    if count == 2:
        return dual
    if 3 <= count <= 10:
        return f"{count} {plural}"
    # Eleven and above take the singular in the accusative — written the same way
    # here, since these messages are unvocalised.
    return f"{count} {singular}"


def invoices(count: int) -> str:
    """"فاتورة واحدة" / "فاتورتان" / "3 فواتير" / "15 فاتورة"."""
    return counted(count, "فاتورة", "فاتورتان", "فواتير")


def rounds(count: int) -> str:
    """"جولة واحدة" / "جولتان" / "3 جولات" / "15 جولة"."""
    return counted(count, "جولة", "جولتان", "جولات")
