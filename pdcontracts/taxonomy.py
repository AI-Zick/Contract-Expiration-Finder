"""Law enforcement software market map.

Two things live here:

1. CATEGORIES -- the product segments a PD buys, each with the procurement
   physics that govern how a displacement sale actually works: typical term
   length, how hard the incumbent is to displace, and how much lead time a
   challenger needs before the money is committed.

2. VENDORS -- the companies selling into each segment. This is the lookup that
   turns "MOTOROLA SOLUTIONS INC" in a city contract register into "this is a
   CAD/RMS incumbent on a 7-year term."

Both are data, not code. Extend them freely -- ``pdcontracts vendors --add``
writes user additions to the config directory so upgrades do not clobber them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Category:
    key: str
    label: str
    # Typical contract length in months. Used to infer an end date when a
    # source gives a start date but no expiration.
    typical_term_months: int
    # 1 (easy to displace) .. 5 (effectively locked in). Drives both priority
    # scoring and how early you have to start.
    stickiness: int
    # Months of lead time a challenger needs before expiration. Sticky,
    # expensive systems require getting into a budget request a year+ early.
    lead_months: int
    notes: str = ""


CATEGORIES: Dict[str, Category] = {
    c.key: c
    for c in [
        Category("cad", "Computer-Aided Dispatch", 84, 5, 24,
                 "Mission-critical 24/7. Replacement is a multi-year project; "
                 "almost always bundled with RMS."),
        Category("rms", "Records Management System", 84, 5, 24,
                 "System of record for reports and arrests. Data migration is "
                 "the single biggest objection."),
        Category("jail", "Jail / Corrections Management", 72, 5, 20),
        Category("911", "911 / NG911 Call Handling", 72, 5, 20,
                 "Often state-funded through 911 surcharge boards, not the PD budget."),
        Category("bwc", "Body-Worn Camera & DEMS", 60, 4, 18,
                 "Camera hardware refresh is the natural switching point. "
                 "Evidence storage is the real lock-in, not the cameras."),
        Category("evidence", "Digital Evidence Management", 60, 4, 15),
        Category("alpr", "Automated License Plate Recognition", 36, 2, 12,
                 "Short terms, subscription pricing, frequent competitive churn."),
        Category("gunshot", "Gunshot Detection", 36, 2, 12,
                 "Politically contested; renewals often go to a public council vote."),
        Category("rtcc", "Real-Time Crime Center / Fusion", 36, 3, 12),
        Category("analytics", "Crime Analytics & Intelligence", 36, 2, 12),
        Category("investigations", "Investigative Data & OSINT", 24, 2, 9),
        Category("forensics", "Digital Forensics", 36, 3, 12),
        Category("dispatch_mobile", "Mobile / Field Reporting", 48, 3, 15),
        Category("ecitation", "E-Citation & Crash Reporting", 48, 3, 12),
        Category("drone", "Drone / DFR Programs", 36, 2, 12),
        Category("scheduling", "Scheduling & Workforce", 36, 2, 9),
        Category("training", "Training & Policy Management", 36, 2, 9,
                 "Low dollar value, fast cycles, frequently a land-and-expand entry point."),
        Category("eis", "Early Intervention / Professional Standards", 36, 2, 9),
        Category("property", "Property & Evidence Room", 48, 3, 12),
        Category("community", "Community Engagement & Notification", 24, 1, 9),
        Category("foia", "Public Records / FOIA & Redaction", 36, 2, 9),
        Category("case", "Case Management / Prosecution Interface", 60, 4, 15),
        Category("radio", "Radio & Communications Infrastructure", 120, 5, 30,
                 "Capital project, not a software sale. Included because it "
                 "reveals the incumbent's overall footprint in the agency."),
        Category("other_software", "Other Public Safety Software", 36, 2, 12),
    ]
}


@dataclass
class Vendor:
    canonical: str
    categories: List[str]
    aliases: List[str] = field(default_factory=list)
    # Parent company, when the brand was acquired. Matters for competitive
    # positioning: a Fusus contract is an Axon relationship.
    parent: str = ""
    notes: str = ""


def _v(canonical, categories, aliases=None, parent="", notes=""):
    return Vendor(canonical, categories, aliases or [], parent, notes)


# The market map. Aliases are matched after normalize_vendor_name(), so
# corporate suffixes and punctuation do not need to be listed.
VENDORS: List[Vendor] = [
    # --- CAD / RMS core systems -------------------------------------------
    _v("Tyler Technologies", ["rms", "cad", "case", "jail", "ecitation"],
       ["tyler", "new world", "new world systems", "brazos", "tyler new world",
        "incode", "socrata"],
       notes="New World for CAD/RMS, Brazos for e-citation."),
    _v("CentralSquare Technologies", ["rms", "cad", "jail", "dispatch_mobile"],
       ["centralsquare", "central square", "superion", "tritech", "zuercher",
        "sungard public sector", "ossi", "public safety corporation"],
       notes="Roll-up of TriTech, Superion, Zuercher, OSSI."),
    _v("Motorola Solutions", ["cad", "rms", "radio", "alpr", "bwc", "911", "rtcc"],
       ["motorola", "premierone", "spillman", "watchguard", "vigilant",
        "vigilant solutions", "commandcentral", "callyo", "openpath",
        "rave mobile safety", "vesta", "airbus ds communications", "avigilon",
        "plant cml", "5f", "orchestrate"],
       notes="Broadest footprint in the market; often the incumbent across "
             "radio, CAD, RMS and cameras at once."),
    _v("Hexagon", ["cad", "rms", "analytics"],
       ["hexagon safety", "intergraph", "hexagon safety and infrastructure"]),
    _v("Mark43", ["rms", "cad", "analytics", "dispatch_mobile"], ["mark 43"]),
    _v("Versaterm", ["rms", "cad", "dispatch_mobile", "evidence"],
       ["versaterm", "commsys", "diverse computing", "eforce", "e force software"]),
    _v("Caliber Public Safety", ["rms", "cad"], ["caliber", "interact911", "interact"]),
    _v("SOMA Global", ["cad", "rms", "jail"], ["soma"]),
    _v("ProPhoenix", ["rms", "cad"], []),
    _v("CODY Systems", ["rms", "analytics"], ["cody"]),
    _v("Niche Technology", ["rms"], ["niche rms"]),
    _v("Axon", ["bwc", "evidence", "rms", "rtcc", "drone", "training", "foia"],
       ["axon", "taser", "evidence com", "vievu", "fusus", "dedrone",
        "axon enterprise", "sky hero"],
       notes="Evidence.com storage is the stickiest part of the Axon stack."),
    _v("Column Technologies", ["case"], ["column"]),

    # --- Body cameras / evidence -------------------------------------------
    _v("Utility Inc", ["bwc", "evidence"], ["utility associates", "bodyworn"]),
    _v("Getac", ["bwc", "evidence", "dispatch_mobile"], ["getac video", "vidtec"]),
    _v("Digital Ally", ["bwc", "evidence"], []),
    _v("Reveal Media", ["bwc"], ["reveal"]),
    _v("i-PRO", ["bwc", "evidence"], ["ipro", "panasonic i pro", "panasonic"]),
    _v("Visual Labs", ["bwc"], []),
    _v("NICE", ["evidence", "case", "911"], ["nice systems", "nice investigate", "nice inform"]),
    _v("VidaNyx", ["evidence"], []),
    _v("Veritone", ["foia", "evidence"], ["veritone redact"]),
    _v("CaseGuard", ["foia", "evidence"], []),
    _v("Milestone Systems", ["evidence", "rtcc"], ["milestone", "xprotect"]),
    _v("Genetec", ["alpr", "rtcc", "evidence"], ["autovu", "clearance"]),

    # --- ALPR / detection ---------------------------------------------------
    _v("Flock Safety", ["alpr", "gunshot", "drone", "rtcc"],
       ["flock", "flock group", "aerodome"],
       notes="Aggressive short-term subscriptions; renewals come up annually."),
    _v("Rekor", ["alpr"], ["rekor systems", "openalpr"]),
    _v("Leonardo", ["alpr"], ["elsag", "leonardo us", "selex"]),
    _v("Neology", ["alpr"], []),
    _v("SoundThinking", ["gunshot", "analytics", "rtcc"],
       ["shotspotter", "sound thinking", "safepointe", "leeds", "forensic logic",
        "coplink"],
       notes="Renewals are frequently a contested public council vote -- "
             "a strong displacement window."),

    # --- RTCC / analytics / investigations ---------------------------------
    _v("Peregrine Technologies", ["rtcc", "analytics"], ["peregrine"]),
    _v("Palantir", ["analytics", "rtcc"], ["palantir usg", "palantir gotham"]),
    _v("LexisNexis", ["investigations", "analytics", "ecitation"],
       ["lexisnexis risk", "lexis nexis", "accurint", "coplogic", "desk officer"]),
    _v("Thomson Reuters", ["investigations"], ["clear", "westlaw", "thomson reuters special services"]),
    _v("Penlink", ["investigations", "forensics"], ["pen link", "cobwebs", "tangles"]),
    _v("Babel Street", ["investigations"], ["babel"]),
    _v("ShadowDragon", ["investigations"], []),
    _v("Skopenow", ["investigations"], []),
    _v("Magnet Forensics", ["forensics"], ["magnet", "graykey", "grayshift", "axiom"]),
    _v("Cellebrite", ["forensics"], ["ufed", "cellebrite di"]),
    _v("Exterro", ["forensics"], ["accessdata", "ftk"]),
    _v("Susteen", ["forensics"], []),
    _v("Oxygen Forensics", ["forensics"], ["oxygen"]),
    _v("Clearview AI", ["investigations"], ["clearview"]),
    _v("ODIN Intelligence", ["investigations"], ["odin"]),
    _v("Carahsoft", ["other_software"], ["carahsoft"],
       notes="Reseller, not an end vendor. Look at the description to find "
             "the actual product behind the paper."),
    _v("SHI International", ["other_software"], ["shi"], notes="Reseller."),
    _v("CDW Government", ["other_software"], ["cdw g", "cdw government"], notes="Reseller."),
    _v("Insight Public Sector", ["other_software"], ["insight"], notes="Reseller."),

    # --- 911 / dispatch -----------------------------------------------------
    _v("RapidSOS", ["911"], []),
    _v("Carbyne", ["911"], []),
    _v("RapidDeploy", ["911", "cad"], []),
    _v("Prepared", ["911"], ["prepared 911", "prepared live"]),
    _v("Intrado", ["911"], ["west safety", "west corporation", "911 datamaster"]),
    _v("Zetron", ["911", "radio"], []),
    _v("Solacom", ["911"], []),
    _v("Comtech", ["911"], ["comtech telecommunications", "solacom"]),
    _v("NGA 911", ["911"], ["nga911"]),

    # --- Drones -------------------------------------------------------------
    _v("Skydio", ["drone"], []),
    _v("BRINC", ["drone"], ["brinc drones"]),
    _v("DroneSense", ["drone"], []),
    _v("Paladin Drones", ["drone"], ["paladin"]),

    # --- Workforce / training / standards ----------------------------------
    _v("NEOGOV", ["training", "scheduling", "eis"], ["powerdms", "power dms", "governmentjobs"]),
    _v("Lexipol", ["training", "eis"], ["cordico", "praetorian"]),
    _v("Vector Solutions", ["training"], ["targetsolutions", "target solutions", "vector lms"]),
    _v("Benchmark Analytics", ["eis", "analytics"], ["benchmark management"]),
    _v("CI Technologies", ["eis"], ["iapro", "blueteam"]),
    _v("Guardian Alliance", ["eis"], ["guardian tracking", "guardian alliance technologies"]),
    _v("InTime Solutions", ["scheduling"], ["intime"]),
    _v("TCP Software", ["scheduling"], ["aladtec", "humanity"]),
    _v("PowerDetails", ["scheduling"], ["power details"]),
    _v("VirTra", ["training"], []),
    _v("Ti Training", ["training"], ["ti training corp"]),
    _v("InVeris", ["training"], ["meggitt training"]),
    _v("Apex Officer", ["training"], []),

    # --- Property & evidence room ------------------------------------------
    _v("FileOnQ", ["property", "evidence"], ["file on q"]),
    _v("Tracker Products", ["property"], ["tracker product"]),
    _v("Porter Lee", ["property", "forensics"], ["beast", "porter lee corporation"]),
    _v("PMI Evidence Tracker", ["property"], ["pmi evidence"]),

    # --- Community / records ------------------------------------------------
    _v("Everbridge", ["community"], ["nixle"]),
    _v("Granicus", ["foia", "community"], ["govqa", "govdelivery"]),
    _v("CivicPlus", ["foia", "community"], ["nextrequest", "civic plus"]),
    _v("JustFOIA", ["foia"], ["just foia"]),
    _v("Zencity", ["community", "analytics"], ["elucd"]),
    _v("Polimorphic", ["community"], []),
    _v("Citizen", ["community"], ["sp0n"]),
    _v("Ring", ["community"], ["neighbors public safety", "ring neighbors"]),
    _v("Axon Citizen", ["community"], [], parent="Axon"),

    # --- Case management / courts ------------------------------------------
    _v("Karpel Solutions", ["case"], ["karpel", "prosecutorbydesign"]),
    _v("Journal Technologies", ["case"], ["journal tech", "ejus"]),
    _v("Equivant", ["case"], ["courtview", "northpointe"]),

    # --- Jail / inmate services --------------------------------------------
    _v("ViaPath", ["jail"], ["global tel link", "gtl", "viapath technologies"]),
    _v("Securus", ["jail"], ["securus technologies", "jpay"]),
    _v("NCIC", ["jail"], ["ncic inmate"]),
    _v("Smart Communications", ["jail"], ["smart comm"]),
]


# --- lookup index ---------------------------------------------------------

def _build_index() -> Dict[str, Vendor]:
    from .normalize import normalize_vendor_name

    index: Dict[str, Vendor] = {}
    for vendor in VENDORS:
        keys = [vendor.canonical] + vendor.aliases
        for key in keys:
            norm = normalize_vendor_name(key)
            if norm and norm not in index:
                index[norm] = vendor
    return index


VENDOR_INDEX: Dict[str, Vendor] = _build_index()

# Vendors that are channel partners rather than product owners. A contract
# with one of these tells you money was spent but not on what, so the
# classifier falls back to reading the description.
RESELLERS = {"Carahsoft", "SHI International", "CDW Government", "Insight Public Sector"}


def register_vendor(vendor: Vendor) -> None:
    """Add a vendor at runtime (used to load user-supplied taxonomy files)."""
    from .normalize import normalize_vendor_name

    VENDORS.append(vendor)
    for key in [vendor.canonical] + vendor.aliases:
        norm = normalize_vendor_name(key)
        if norm:
            VENDOR_INDEX[norm] = vendor


def get_category(key: str) -> Optional[Category]:
    return CATEGORIES.get(key)
