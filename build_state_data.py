"""
build_state_data — assemble a small, real US-state dataset for choropleth maps.

Six metrics per state (50 + DC), from public US sources. Density is computed
from population / land area; everything else is a curated, documented figure so
the build needs no API key. Output keyed by state NAME so it joins directly with
web/data/states.json (which carries properties.name).

    web/data/us_state_stats.json
        {metrics:[{key,label,unit,fmt,scheme,desc}], year, states:{Name:{...}}}

Sources: 2020 Decennial Census (population), Census land area (sq mi),
ACS 2022 1-year estimates (median household income, poverty rate, bachelor's+).
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "web", "data", "us_state_stats.json")

# postal -> full state name (matches names in web/data/states.json)
NAME = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

# population (2020 census), land_sqmi (census land area),
# income (ACS22 median household $), poverty (% ACS22), bachelors (% 25+ ACS22)
#       postal:  (pop,        land_sqmi, income, poverty, bachelors)
RAW = {
    "AL": (5024279, 50645, 59609, 16.0, 27.0),
    "AK": (733391, 570641, 86370, 10.6, 30.7),
    "AZ": (7151502, 113594, 72581, 12.6, 31.5),
    "AR": (3011524, 52035, 56335, 16.3, 24.2),
    "CA": (39538223, 155779, 91905, 12.2, 36.0),
    "CO": (5773714, 103642, 87598, 9.7, 44.4),
    "CT": (3605944, 4842, 90213, 10.1, 41.1),
    "DE": (989948, 1949, 79325, 11.6, 34.5),
    "DC": (689545, 61, 101722, 14.0, 64.8),
    "FL": (21538187, 53625, 67917, 13.1, 32.0),
    "GA": (10711908, 57513, 71355, 14.0, 34.0),
    "HI": (1455271, 6423, 94814, 10.2, 35.5),
    "ID": (1839106, 82643, 70214, 11.0, 30.5),
    "IL": (12812508, 55519, 78433, 11.6, 37.5),
    "IN": (6785528, 35826, 69477, 12.6, 28.6),
    "IA": (3190369, 55857, 70571, 11.1, 30.8),
    "KS": (2937880, 81759, 69747, 11.6, 35.0),
    "KY": (4505836, 39486, 60183, 16.5, 26.5),
    "LA": (4657757, 43204, 57852, 19.6, 26.4),
    "ME": (1362359, 30843, 68251, 10.9, 35.6),
    "MD": (6177224, 9707, 98461, 9.6, 42.6),
    "MA": (7029917, 7800, 96505, 10.4, 47.2),
    "MI": (10077331, 56539, 68505, 13.4, 32.0),
    "MN": (5706494, 79627, 84313, 9.6, 39.5),
    "MS": (2961279, 46923, 52719, 19.1, 24.8),
    "MO": (6154913, 68742, 65920, 12.6, 31.3),
    "MT": (1084225, 145546, 66341, 12.1, 35.4),
    "NE": (1961504, 76824, 71722, 10.7, 34.5),
    "NV": (3104614, 109781, 71646, 12.3, 27.5),
    "NH": (1377529, 8953, 90845, 7.2, 39.7),
    "NJ": (9288994, 7354, 97126, 10.2, 43.2),
    "NM": (2117522, 121298, 58722, 18.4, 29.6),
    "NY": (20201249, 47126, 81386, 14.3, 39.6),
    "NC": (10439388, 48618, 66186, 13.4, 35.5),
    "ND": (779094, 69001, 73959, 10.7, 32.4),
    "OH": (11799448, 40861, 66990, 13.4, 31.2),
    "OK": (3959353, 68595, 61364, 15.6, 27.0),
    "OR": (4237256, 95988, 76632, 12.1, 36.7),
    "PA": (13002700, 44743, 73170, 12.0, 34.5),
    "RI": (1097379, 1034, 81370, 11.4, 37.5),
    "SC": (5118425, 30061, 63623, 14.2, 31.5),
    "SD": (886667, 75811, 69457, 12.4, 31.9),
    "TN": (6910840, 41235, 64035, 13.6, 30.0),
    "TX": (29145505, 261232, 73035, 14.0, 32.3),
    "UT": (3271616, 82170, 86833, 8.9, 37.0),
    "VT": (643077, 9217, 74014, 10.4, 42.5),
    "VA": (8631393, 39490, 87249, 10.2, 42.0),
    "WA": (7705281, 66456, 90325, 10.0, 39.9),
    "WV": (1793716, 24038, 55217, 16.7, 22.7),
    "WI": (5893718, 54158, 72458, 10.8, 32.8),
    "WY": (576851, 97093, 72495, 11.0, 29.5),
}

METRICS = [
    {"key": "density", "label": "Population density", "unit": "/mi²", "fmt": "int",
     "scheme": "viridis", "desc": "Residents per square mile (2020 Census)"},
    {"key": "pop", "label": "Total population", "unit": "", "fmt": "int",
     "scheme": "plasma", "desc": "Resident population (2020 Census)"},
    {"key": "income", "label": "Median household income", "unit": "$", "fmt": "usd",
     "scheme": "cividis", "desc": "Median household income (ACS 2022)"},
    {"key": "land", "label": "Land area", "unit": "mi²", "fmt": "int",
     "scheme": "YlGn", "desc": "Land area in square miles (Census)"},
    {"key": "poverty", "label": "Poverty rate", "unit": "%", "fmt": "pct",
     "scheme": "magma", "desc": "Share of people below the poverty line (ACS 2022)"},
    {"key": "bachelors", "label": "Bachelor's degree or higher", "unit": "%", "fmt": "pct",
     "scheme": "GnBu", "desc": "Share of adults 25+ with a bachelor's+ (ACS 2022)"},
]


def main():
    states = {}
    for postal, (pop, land, income, poverty, bach) in RAW.items():
        states[NAME[postal]] = {
            "postal": postal,
            "density": round(pop / land, 1),
            "pop": pop,
            "income": income,
            "land": land,
            "poverty": poverty,
            "bachelors": bach,
        }
    payload = {"metrics": METRICS, "year": "2020–2022", "states": states}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"wrote {OUT}  ({len(states)} states, {len(METRICS)} metrics)")
    # quick sanity: densest + sparsest
    by_d = sorted(states.items(), key=lambda kv: kv[1]["density"])
    print("  sparsest:", by_d[0][0], by_d[0][1]["density"], "/mi^2")
    print("  densest :", by_d[-1][0], by_d[-1][1]["density"], "/mi^2")


if __name__ == "__main__":
    main()
