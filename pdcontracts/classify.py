"""Decide what a contract record actually is.

Given a vendor string and a free-text description, work out:
  * which known vendor it belongs to (exact, then contiguous-token match)
  * which product category it falls in
  * whether it is software at all
  * how much to trust that answer

The order matters. A vendor match is far more reliable than keyword matching on
a description, so vendor wins whenever it is available, and the description is
only used to disambiguate multi-category vendors or to rescue records from
resellers and unknown companies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .normalize import normalize_vendor_name
from .taxonomy import RESELLERS, VENDOR_INDEX, Vendor

# Description keywords per category, used when the vendor is unknown or sells
# into several segments. Ordered most-specific-first within each list.
CATEGORY_KEYWORDS = {
    "cad": ["computer aided dispatch", "computer-aided dispatch", "cad system", "dispatch system"],
    "rms": ["records management", "rms system", "police records", "incident reporting system"],
    "bwc": ["body worn camera", "body-worn camera", "bodycam", "body camera", "bwc"],
    "evidence": ["digital evidence", "evidence management", "evidence.com", "dems"],
    "alpr": ["license plate reader", "license plate recognition", "alpr", "lpr camera", "plate reader"],
    "gunshot": ["gunshot detection", "gunfire detection", "acoustic detection", "shotspotter"],
    "rtcc": ["real time crime center", "real-time crime center", "rtcc", "fusion center"],
    "analytics": ["crime analytics", "crime analysis", "predictive policing", "intelligence platform"],
    "investigations": ["investigative database", "public records search", "osint", "open source intelligence",
                       "social media monitoring", "skip trace"],
    "forensics": ["digital forensics", "mobile forensics", "forensic extraction", "cell phone extraction"],
    "911": ["911 call handling", "next generation 911", "ng911", "nena", "psap", "call taking"],
    "jail": ["jail management", "inmate management", "corrections management", "detention management"],
    "ecitation": ["e-citation", "ecitation", "electronic citation", "crash report", "accident report"],
    "dispatch_mobile": ["mobile data terminal", "field reporting", "mdt", "mobile data computer"],
    "drone": ["unmanned aircraft", "drone as first responder", "uas program", "sUAS", "drone"],
    "scheduling": ["scheduling software", "workforce management", "timekeeping", "shift scheduling",
                   "off duty", "extra duty"],
    "training": ["training management", "policy management", "learning management", "lms",
                 "policy manual", "in-service training"],
    "eis": ["early intervention", "internal affairs", "professional standards", "use of force tracking"],
    "property": ["property and evidence", "evidence room", "property room", "barcode evidence"],
    "community": ["mass notification", "community engagement", "public alerting", "tip line"],
    "foia": ["public records request", "foia", "redaction software", "records request portal"],
    "case": ["case management", "prosecution", "district attorney case"],
    "radio": ["radio system", "p25", "land mobile radio", "lmr", "astro 25", "subscriber radio"],
}

# Generic evidence that a line item is software/SaaS rather than vehicles,
# uniforms, ammunition, or construction.
SOFTWARE_HINTS = re.compile(
    r"\b(software|saas|software as a service|licens\w*|subscription|maintenance|"
    r"support agreement|hosting|hosted|cloud|platform|system|application|"
    r"annual support|user fees?|seats?|module|upgrade|implementation|"
    r"data storage|analytics|portal|interface|api)\b",
    re.I,
)

# Strong evidence it is NOT a software purchase, even if a software vendor is
# on the paper (Axon sells Tasers; Motorola sells radios).
NON_SOFTWARE_HINTS = re.compile(
    r"\b(vehicle|patrol car|ammunition|ammo|firearm|weapon|taser cartridge|cartridges|"
    r"uniform|apparel|body armor|vest|fuel|construction|renovation|roof|re?pav\w+|"
    r"resurfac\w+|landscap\w+|mowing|snow removal|janitorial|towing|k-?9|canine|"
    r"furniture|overtime|salary|insurance premium|security guard services|"
    r"legal services|settlement|lease of real property)\b",
    re.I,
)


@dataclass
class Classification:
    vendor_canonical: str
    category: str
    is_software: Optional[bool]
    confidence: float
    reasons: List[str]


def match_vendor(vendor_raw: str) -> Tuple[Optional[Vendor], float]:
    """Find the known vendor behind a raw vendor string.

    Returns the vendor and a confidence. Exact normalized match is 0.95;
    a contiguous-token match inside a longer string is 0.8.
    """
    norm = normalize_vendor_name(vendor_raw)
    if not norm:
        return None, 0.0

    exact = VENDOR_INDEX.get(norm)
    if exact:
        return exact, 0.95

    tokens = norm.split()
    # Try progressively shorter contiguous spans so "motorola solutions credit
    # corp" still resolves to Motorola.
    for span in range(len(tokens), 0, -1):
        for start in range(0, len(tokens) - span + 1):
            candidate = " ".join(tokens[start:start + span])
            # Guard against one short token producing a spurious hit.
            if span == 1 and len(candidate) < 5:
                continue
            vendor = VENDOR_INDEX.get(candidate)
            if vendor:
                return vendor, 0.8
    return None, 0.0


def category_from_text(text: str) -> Tuple[Optional[str], float]:
    """Infer a category from free text. Longer phrase matches win."""
    if not text:
        return None, 0.0
    low = text.lower()
    best: Optional[str] = None
    best_len = 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in low and len(keyword) > best_len:
                best, best_len = category, len(keyword)
    if not best:
        return None, 0.0
    # A long, distinctive phrase is much better evidence than a 3-letter acronym.
    confidence = 0.75 if best_len >= 12 else 0.5
    return best, confidence


def is_software_purchase(description: str, vendor: Optional[Vendor]) -> Tuple[Optional[bool], str]:
    """Decide whether the line item is software, and say why."""
    text = description or ""
    if NON_SOFTWARE_HINTS.search(text) and not SOFTWARE_HINTS.search(text):
        return False, "description describes goods/services, not software"
    if SOFTWARE_HINTS.search(text):
        return True, "description mentions software/subscription/licensing"
    if vendor and vendor.canonical not in RESELLERS:
        return True, f"{vendor.canonical} is a known public safety software vendor"
    if not text:
        return None, "no description available"
    return None, "insufficient evidence"


def classify(vendor_raw: str, description: str = "", hint_category: str = "") -> Classification:
    """Classify a single contract record."""
    reasons: List[str] = []
    vendor, vendor_conf = match_vendor(vendor_raw)
    text_category, text_conf = category_from_text(f"{description} {vendor_raw}")

    canonical = vendor.canonical if vendor else ""
    if vendor:
        reasons.append(f"vendor matched: {vendor.canonical}")
    else:
        reasons.append("vendor not in taxonomy")

    category = ""
    confidence = 0.0

    if vendor and vendor.canonical not in RESELLERS:
        if len(vendor.categories) == 1:
            category = vendor.categories[0]
            confidence = vendor_conf
            reasons.append("vendor sells a single category")
        elif text_category and text_category in vendor.categories:
            # Description agrees with something the vendor actually sells --
            # the strongest signal available.
            category = text_category
            confidence = min(0.95, vendor_conf + 0.05)
            reasons.append("description agrees with vendor's product line")
        elif text_category:
            category = text_category
            confidence = max(text_conf, 0.55)
            reasons.append("description outweighed multi-category vendor")
        else:
            # Fall back to the vendor's primary (first-listed) segment.
            category = vendor.categories[0]
            confidence = 0.5
            reasons.append("defaulted to vendor's primary category")
    elif text_category:
        category = text_category
        confidence = text_conf
        reasons.append("category inferred from description only")
    elif hint_category:
        category = hint_category
        confidence = 0.3
        reasons.append("category supplied by source")

    software, software_reason = is_software_purchase(description, vendor)
    reasons.append(software_reason)

    if category == "radio" and not re.search(
        r"\b(software|saas|licens\w*|subscription|application)\b", description or "", re.I
    ):
        # Radio work is a capital/infrastructure buy. Keep the record for
        # incumbent-footprint context, but do not call it a software contract.
        software = False
        reasons.append("radio infrastructure, not a software purchase")

    if software is False:
        # Keep the vendor attribution but do not claim a software category.
        confidence = min(confidence, 0.3)
    elif software and not category:
        category = "other_software"
        confidence = max(confidence, 0.3)
        reasons.append("software but category unknown")

    return Classification(
        vendor_canonical=canonical or vendor_raw.strip(),
        category=category,
        is_software=software,
        confidence=round(confidence, 2),
        reasons=reasons,
    )
