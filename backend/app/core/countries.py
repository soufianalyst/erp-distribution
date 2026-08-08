"""Country reference data for the settings control panel.

Kept as a curated list rather than a full ISO dump: the panel is a picker for a
wholesale food distributor, and a short list of the markets they actually operate
in is easier to use than 250 entries. Each country carries its usual currency so
choosing a country can suggest the currency instead of asking twice.

Codes are ISO 3166-1 alpha-2. A tax rate with no country applies everywhere;
see SettingsService.list_tax_rates.
"""

from typing import NamedTuple


class Country(NamedTuple):
    code: str
    name: str  # Arabic name, shown in the UI
    currency_code: str
    currency_symbol: str


# Gulf, Levant, and North Africa first — the likely markets — then a short tail
# of common trade partners. Add to this list as the business expands.
COUNTRIES: list[Country] = [
    Country("SA", "المملكة العربية السعودية", "SAR", "ر.س"),
    Country("AE", "الإمارات العربية المتحدة", "AED", "د.إ"),
    Country("KW", "الكويت", "KWD", "د.ك"),
    Country("QA", "قطر", "QAR", "ر.ق"),
    Country("BH", "البحرين", "BHD", "د.ب"),
    Country("OM", "عُمان", "OMR", "ر.ع"),
    Country("YE", "اليمن", "YER", "ر.ي"),
    Country("JO", "الأردن", "JOD", "د.أ"),
    Country("PS", "فلسطين", "ILS", "₪"),
    Country("LB", "لبنان", "LBP", "ل.ل"),
    Country("SY", "سوريا", "SYP", "ل.س"),
    Country("IQ", "العراق", "IQD", "د.ع"),
    Country("EG", "مصر", "EGP", "ج.م"),
    Country("LY", "ليبيا", "LYD", "د.ل"),
    Country("TN", "تونس", "TND", "د.ت"),
    Country("DZ", "الجزائر", "DZD", "د.ج"),
    Country("MA", "المغرب", "MAD", "د.م"),
    Country("MR", "موريتانيا", "MRU", "أ.م"),
    Country("SD", "السودان", "SDG", "ج.س"),
    Country("SO", "الصومال", "SOS", "ش.ص"),
    Country("DJ", "جيبوتي", "DJF", "ف.ج"),
    Country("KM", "جزر القمر", "KMF", "ف.ق"),
    Country("TR", "تركيا", "TRY", "₺"),
    Country("IR", "إيران", "IRR", "ر.إ"),
    Country("PK", "باكستان", "PKR", "₨"),
    Country("IN", "الهند", "INR", "₹"),
    Country("CN", "الصين", "CNY", "¥"),
    Country("GB", "المملكة المتحدة", "GBP", "£"),
    Country("US", "الولايات المتحدة", "USD", "$"),
    Country("DE", "ألمانيا", "EUR", "€"),
    Country("FR", "فرنسا", "EUR", "€"),
    Country("NL", "هولندا", "EUR", "€"),
]

COUNTRIES_BY_CODE: dict[str, Country] = {c.code: c for c in COUNTRIES}


def is_valid_country(code: str | None) -> bool:
    """None is valid: it means "applies everywhere" / "not specified"."""
    return code is None or code in COUNTRIES_BY_CODE


def country_name(code: str | None) -> str | None:
    """Arabic name for a country code; None when unset or unknown."""
    country = COUNTRIES_BY_CODE.get(code) if code else None
    return country.name if country else None
