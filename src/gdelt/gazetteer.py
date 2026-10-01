"""Hand-made gazetteer: Selangor/KL place names -> (district, lat, lon).

Districts: the 9 Selangor districts, Kuala Lumpur and Putrajaya. Coordinates are approximate (about 1 to 3 km),
good enough to pick the nearest ERA5 cell, not for mapping. Names are matched case-insensitively with word
boundaries, longest first. Extend as new events mention new places.
"""
import re

# name: (district, lat, lon)
PLACES = {
    # --- Kuala Lumpur
    "kuala lumpur": ("Kuala Lumpur", 3.139, 101.687), "klcc": ("Kuala Lumpur", 3.158, 101.712),
    "jalan ipoh": ("Kuala Lumpur", 3.188, 101.683), "kepong": ("Kuala Lumpur", 3.214, 101.638),
    "setapak": ("Kuala Lumpur", 3.200, 101.719), "sentul": ("Kuala Lumpur", 3.181, 101.689),
    "bangsar": ("Kuala Lumpur", 3.130, 101.671), "pudu": ("Kuala Lumpur", 3.134, 101.713),
    "chow kit": ("Kuala Lumpur", 3.167, 101.698), "jalan duta": ("Kuala Lumpur", 3.172, 101.673),
    "jalan raja chulan": ("Kuala Lumpur", 3.150, 101.710), "cheras": ("Kuala Lumpur", 3.108, 101.738),
    "wangsa maju": ("Kuala Lumpur", 3.205, 101.735), "segambut": ("Kuala Lumpur", 3.188, 101.665),
    "mont kiara": ("Kuala Lumpur", 3.172, 101.651), "bukit bintang": ("Kuala Lumpur", 3.146, 101.711),
    "sri petaling": ("Kuala Lumpur", 3.062, 101.688), "bukit jalil": ("Kuala Lumpur", 3.057, 101.692),
    "taman desa": ("Kuala Lumpur", 3.100, 101.685), "kampung bohol": ("Kuala Lumpur", 3.160, 101.697),
    "kampung baru": ("Kuala Lumpur", 3.163, 101.707), "batu muda": ("Kuala Lumpur", 3.210, 101.680),
    "jalan semantan": ("Kuala Lumpur", 3.151, 101.664), "jalan tuanku abdul halim": ("Kuala Lumpur", 3.180, 101.676),
    "jalan pantai baharu": ("Kuala Lumpur", 3.110, 101.667), "taman tun dr ismail": ("Kuala Lumpur", 3.137, 101.629),
    "brickfields": ("Kuala Lumpur", 3.133, 101.686), "world trade centre": ("Kuala Lumpur", 3.166, 101.700),
    "klang valley": ("Kuala Lumpur", 3.139, 101.687),  # generic; lowest priority (see GENERIC)
    # --- Petaling
    "petaling jaya": ("Petaling", 3.107, 101.607), "subang jaya": ("Petaling", 3.049, 101.581),
    "subang": ("Petaling", 3.131, 101.549), "usj": ("Petaling", 3.039, 101.583),
    "puchong": ("Petaling", 3.020, 101.617), "shah alam": ("Petaling", 3.073, 101.518),
    "kota damansara": ("Petaling", 3.150, 101.585), "damansara": ("Petaling", 3.150, 101.610),
    "seri kembangan": ("Petaling", 3.020, 101.708), "sungai buloh": ("Petaling", 3.207, 101.580),
    "bandar utama": ("Petaling", 3.147, 101.610), "kelana jaya": ("Petaling", 3.103, 101.605),
    "taman sri muda": ("Petaling", 3.047, 101.540), "i-city": ("Petaling", 3.065, 101.485),
    "bukit jelutong": ("Petaling", 3.110, 101.530), "petaling": ("Petaling", 3.090, 101.600),
    # --- Klang
    "klang": ("Klang", 3.045, 101.445), "meru": ("Klang", 3.088, 101.427), "kapar": ("Klang", 3.140, 101.381),
    "port klang": ("Klang", 3.000, 101.390), "bandar botanic": ("Klang", 3.002, 101.446),
    "setia alam": ("Klang", 3.109, 101.449), "bukit raja": ("Klang", 3.077, 101.478),
    "taman sentosa": ("Klang", 3.071, 101.437), "pulau indah": ("Klang", 2.987, 101.343),
    "taman sri jaya": ("Klang", 3.100, 101.420), "bandar bukit tinggi": ("Klang", 3.000, 101.440),
    # --- Gombak
    "gombak": ("Gombak", 3.252, 101.722), "selayang": ("Gombak", 3.250, 101.649), "batu caves": ("Gombak", 3.237, 101.684),
    "rawang": ("Gombak", 3.321, 101.576), "taman selayang": ("Gombak", 3.250, 101.660),
    # --- Hulu Langat
    "ampang": ("Hulu Langat", 3.150, 101.762), "kajang": ("Hulu Langat", 2.993, 101.787),
    "bangi": ("Hulu Langat", 2.969, 101.769), "semenyih": ("Hulu Langat", 2.950, 101.843),
    "hulu langat": ("Hulu Langat", 3.100, 101.800), "ulu langat": ("Hulu Langat", 3.100, 101.800),
    "balakong": ("Hulu Langat", 3.019, 101.742),
    # --- Sepang / Putrajaya
    "sepang": ("Sepang", 2.690, 101.750), "dengkil": ("Sepang", 2.865, 101.676), "cyberjaya": ("Sepang", 2.920, 101.656),
    "salak tinggi": ("Sepang", 2.800, 101.730), "klia": ("Sepang", 2.746, 101.707), "putrajaya": ("Putrajaya", 2.926, 101.696),
    # --- Kuala Langat
    "banting": ("Kuala Langat", 2.816, 101.502), "kuala langat": ("Kuala Langat", 2.800, 101.480),
    "telok panglima garang": ("Kuala Langat", 2.950, 101.500), "jenjarom": ("Kuala Langat", 2.880, 101.530),
    "bukit changgang": ("Kuala Langat", 2.840, 101.530), "taman langat utama": ("Kuala Langat", 2.820, 101.520),
    "morib": ("Kuala Langat", 2.750, 101.430),
    # --- Kuala Selangor / Sabak Bernam / Hulu Selangor
    "kuala selangor": ("Kuala Selangor", 3.340, 101.250), "tanjong karang": ("Kuala Selangor", 3.430, 101.170),
    "tanjung karang": ("Kuala Selangor", 3.430, 101.170), "puncak alam": ("Kuala Selangor", 3.236, 101.434),
    "bestari jaya": ("Kuala Selangor", 3.370, 101.400), "ijok": ("Kuala Selangor", 3.350, 101.310),
    "sabak bernam": ("Sabak Bernam", 3.760, 101.100), "sekinchan": ("Sabak Bernam", 3.500, 101.110),
    "sungai besar": ("Sabak Bernam", 3.670, 101.000),
    "kuala kubu bharu": ("Hulu Selangor", 3.560, 101.650), "kuala kubu baru": ("Hulu Selangor", 3.560, 101.650),
    "batang kali": ("Hulu Selangor", 3.430, 101.640), "hulu selangor": ("Hulu Selangor", 3.600, 101.600),
    "serendah": ("Hulu Selangor", 3.380, 101.600),
    # --- state level (lowest priority)
    "selangor": ("Selangor (unspecified)", 3.300, 101.500),
}
GENERIC = {"klang valley", "selangor", "kuala lumpur"}  # too coarse when a specific place is also present
_NAMES = sorted(PLACES, key=len, reverse=True)
_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(n) for n in _NAMES) + r")(?![A-Za-z])", re.I)


def find_places(text: str) -> list[str]:
    """Gazetteer names in text, in order of appearance, generic names dropped if a specific one is present."""
    found = [m.group(1).lower() for m in _RE.finditer(text)]
    specific = [f for f in found if f not in GENERIC]
    return specific if specific else found
