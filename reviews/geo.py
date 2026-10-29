"""Regions and cities of Kyrgyzstan.

Seven oblasts plus the two cities of republican significance (Bishkek, Osh).
Names are stored in Russian in the database and translated with gettext,
so the same code works for the memory and the Django repository.
"""
from django.utils.translation import gettext, gettext_lazy as _

# (code, name, kind) in display order: republican cities first, then oblasts A-Z (ru)
REGIONS = [
    ("bishkek", _("г. Бишкек"), "city"),
    ("osh-city", _("г. Ош"), "city"),
    ("batken", _("Баткенская область"), "oblast"),
    ("jalal-abad", _("Джалал-Абадская область"), "oblast"),
    ("issyk-kul", _("Иссык-Кульская область"), "oblast"),
    ("naryn", _("Нарынская область"), "oblast"),
    ("osh", _("Ошская область"), "oblast"),
    ("talas", _("Таласская область"), "oblast"),
    ("chuy", _("Чуйская область"), "oblast"),
]
REGION_CODES = [code for code, _name, _kind in REGIONS]
REGION_CHOICES = [(code, name) for code, name, _kind in REGIONS]
_REGION_BY_CODE = {code: (name, kind) for code, name, kind in REGIONS}

# Russian city name (as stored in School.city) -> region code
CITY_REGION = {
    "Бишкек": "bishkek",
    "Ош": "osh-city",
    "Баткен": "batken",
    "Кызыл-Кия": "batken",
    "Сулюкта": "batken",
    "Жалал-Абад": "jalal-abad",
    "Таш-Кумыр": "jalal-abad",
    "Кара-Куль": "jalal-abad",
    "Майлуу-Суу": "jalal-abad",
    "Каракол": "issyk-kul",
    "Балыкчы": "issyk-kul",
    "Чолпон-Ата": "issyk-kul",
    "Нарын": "naryn",
    "Узген": "osh",
    "Кара-Суу": "osh",
    "Талас": "talas",
    "Токмок": "chuy",
    "Кант": "chuy",
    "Кара-Балта": "chuy",
    "Шопоков": "chuy",
    "Ивановка": "chuy",
}

# marked for makemessages so the .po files carry every city name
_CITY_LABELS = [
    _("Бишкек"), _("Ош"), _("Баткен"), _("Кызыл-Кия"), _("Сулюкта"), _("Жалал-Абад"), _("Таш-Кумыр"),
    _("Кара-Куль"), _("Майлуу-Суу"), _("Каракол"), _("Балыкчы"), _("Чолпон-Ата"), _("Нарын"), _("Узген"),
    _("Кара-Суу"), _("Талас"), _("Токмок"), _("Кант"), _("Кара-Балта"), _("Шопоков"), _("Ивановка"),
]

REGION_PREFIX = "r:"  # value of a "whole region" option in the city filter


def region_for_city(city):
    return CITY_REGION.get((city or "").strip(), "")


def region_name(code):
    entry = _REGION_BY_CODE.get(code)
    return str(entry[0]) if entry else ""


def region_kind(code):
    entry = _REGION_BY_CODE.get(code)
    return entry[1] if entry else ""


def city_name(city):
    return gettext(city) if city else ""


def parse_place(value):
    """'r:chuy' -> ('chuy', ''); 'Токмок' -> ('', 'Токмок'); unknown region -> ('', '')."""
    value = (value or "").strip()
    if value.startswith(REGION_PREFIX):
        code = value[len(REGION_PREFIX):]
        return (code, "") if code in _REGION_BY_CODE else ("", "")
    return "", value


def build_locations(schools):
    """Group distinct cities of the given schools by region, in fixed region order.

    Returns [{"code", "name", "kind", "value", "cities": [{"name", "label", "count"}], "count"}].
    Every region is listed (an oblast without universities has count 0) so the
    filter always shows the whole country. Cities are unique and sorted.
    """
    per_region = {code: {} for code in REGION_CODES}
    for s in schools:
        code = s.region or region_for_city(s.city)
        if code not in per_region or not s.city:
            continue
        per_region[code][s.city] = per_region[code].get(s.city, 0) + 1
    out = []
    for code, name, kind in REGIONS:
        cities = [{"name": c, "label": city_name(c), "count": n}
                  for c, n in sorted(per_region[code].items(), key=lambda kv: city_name(kv[0]).lower())]
        out.append({
            "code": code, "name": str(name), "kind": kind, "value": REGION_PREFIX + code,
            "cities": cities, "count": sum(c["count"] for c in cities),
        })
    return out


def filter_schools(schools, region="", city=""):
    if city:
        return [s for s in schools if s.city == city]
    if region:
        return [s for s in schools if (s.region or region_for_city(s.city)) == region]
    return list(schools)
