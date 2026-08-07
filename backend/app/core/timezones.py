"""Timezone reference data for the settings control panel.

Curated in the same spirit as `countries`: a wholesale distributor needs to pick the
zone their working day runs on, not scroll the ~600 entries the IANA database holds.
One per market the country list covers, plus UTC.

The zone matters because the company's midnight is where a business day starts — the
cashier's closing report and any other figure asked for "by day". See
`app/core/business_day` for what goes wrong when the server's zone is used instead.
"""

from typing import NamedTuple


class Timezone(NamedTuple):
    name: str  # IANA identifier, stored in company_settings.timezone
    label: str  # Arabic city name shown in the picker


# Ordered to match the country list, so the panel reads consistently. Offsets are
# deliberately not hard-coded here — they are derived from the zone at display time,
# because a fixed "+03" written in a list is wrong the moment a country changes its
# rules, and several in this region have.
TIMEZONES: list[Timezone] = [
    Timezone("Asia/Riyadh", "الرياض"),
    Timezone("Asia/Dubai", "دبي"),
    Timezone("Asia/Kuwait", "الكويت"),
    Timezone("Asia/Qatar", "الدوحة"),
    Timezone("Asia/Bahrain", "المنامة"),
    Timezone("Asia/Muscat", "مسقط"),
    Timezone("Asia/Aden", "عدن"),
    Timezone("Asia/Amman", "عمّان"),
    Timezone("Asia/Hebron", "فلسطين"),
    Timezone("Asia/Beirut", "بيروت"),
    Timezone("Asia/Damascus", "دمشق"),
    Timezone("Asia/Baghdad", "بغداد"),
    Timezone("Africa/Cairo", "القاهرة"),
    Timezone("Africa/Khartoum", "الخرطوم"),
    Timezone("Africa/Tripoli", "طرابلس"),
    Timezone("Africa/Tunis", "تونس"),
    Timezone("Africa/Algiers", "الجزائر"),
    Timezone("Africa/Casablanca", "الدار البيضاء"),
    Timezone("Asia/Istanbul", "إستانبول"),
    Timezone("UTC", "التوقيت العالمي (UTC)"),
]
