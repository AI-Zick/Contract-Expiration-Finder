"""Public records request generator.

Most agencies publish nothing. For those, a records request is the only way to
get a contract term, and it is cheap: one templated letter per agency, sent to
the city clerk or records custodian. This generates them, worded narrowly so
they are hard to deny and cheap for the agency to fulfill -- broad requests get
fee estimates and delays, specific ones get answered.

The statute names below are the commonly used names for each state's public
records law. Response deadlines vary and change, so the letter does not assert
one; it cites the statute and asks for an acknowledgement.
"""

from __future__ import annotations

import datetime as _dt
from typing import List, Optional

STATE_STATUTES = {
    "AL": "Alabama Open Records Act",
    "AK": "Alaska Public Records Act",
    "AZ": "Arizona Public Records Law",
    "AR": "Arkansas Freedom of Information Act",
    "CA": "California Public Records Act",
    "CO": "Colorado Open Records Act",
    "CT": "Connecticut Freedom of Information Act",
    "DE": "Delaware Freedom of Information Act",
    "DC": "District of Columbia Freedom of Information Act",
    "FL": "Florida Public Records Act (Chapter 119, Florida Statutes)",
    "GA": "Georgia Open Records Act",
    "HI": "Hawaii Uniform Information Practices Act",
    "ID": "Idaho Public Records Act",
    "IL": "Illinois Freedom of Information Act",
    "IN": "Indiana Access to Public Records Act",
    "IA": "Iowa Open Records Law (Chapter 22)",
    "KS": "Kansas Open Records Act",
    "KY": "Kentucky Open Records Act",
    "LA": "Louisiana Public Records Law",
    "ME": "Maine Freedom of Access Act",
    "MD": "Maryland Public Information Act",
    "MA": "Massachusetts Public Records Law",
    "MI": "Michigan Freedom of Information Act",
    "MN": "Minnesota Government Data Practices Act",
    "MS": "Mississippi Public Records Act",
    "MO": "Missouri Sunshine Law",
    "MT": "Montana Public Records Law",
    "NE": "Nebraska Public Records Statutes",
    "NV": "Nevada Public Records Act",
    "NH": "New Hampshire Right-to-Know Law",
    "NJ": "New Jersey Open Public Records Act",
    "NM": "New Mexico Inspection of Public Records Act",
    "NY": "New York Freedom of Information Law",
    "NC": "North Carolina Public Records Law",
    "ND": "North Dakota Open Records Statute",
    "OH": "Ohio Public Records Act",
    "OK": "Oklahoma Open Records Act",
    "OR": "Oregon Public Records Law",
    "PA": "Pennsylvania Right-to-Know Law",
    "RI": "Rhode Island Access to Public Records Act",
    "SC": "South Carolina Freedom of Information Act",
    "SD": "South Dakota Open Records Law",
    "TN": "Tennessee Public Records Act",
    "TX": "Texas Public Information Act",
    "UT": "Utah Government Records Access and Management Act",
    "VT": "Vermont Public Records Act",
    "VA": "Virginia Freedom of Information Act",
    "WA": "Washington Public Records Act",
    "WV": "West Virginia Freedom of Information Act",
    "WI": "Wisconsin Public Records Law",
    "WY": "Wyoming Public Records Act",
}

DEFAULT_SYSTEMS = [
    "Records Management System (RMS)",
    "Computer-Aided Dispatch (CAD)",
    "Mobile Data Terminal / mobile field reporting software",
]

TEMPLATE = """{date}

Public Records Custodian
{agency}
{address}

Re: Public records request - law enforcement software contracts

To the Records Custodian:

Under the {statute}, I request copies of the following records concerning the
{agency}'s public safety software:

1. The current contract, purchase order, or master agreement for each of the
   following systems, including all amendments, extensions, and exhibits:
{systems_block}

2. For each contract identified above, records sufficient to show:
   a. the vendor name;
   b. the contract start date and expiration date;
   c. the number and length of any remaining renewal or extension options;
   d. the total contract value and the current annual or recurring amount;
   e. any notice period required to decline renewal.

3. The most recent invoice or annual maintenance/subscription statement from
   each vendor identified above.

4. Any solicitation (RFP, RFQ, or ITB) issued or planned for the replacement of
   any system listed above within the next twenty-four months.

To reduce cost and processing time: I will accept electronic copies delivered by
email, and existing reports or exports are acceptable in place of individually
gathered documents. If a contract summary or vendor register already contains
items 2(a) through 2(e), producing that record alone will satisfy that item.

If any portion of this request is denied, please cite the specific exemption
relied upon and produce the remaining non-exempt portions. If fees are expected
to exceed {fee_cap}, please contact me with an estimate before proceeding.

Please acknowledge receipt of this request. I am happy to narrow the scope if
that would speed processing.

Thank you for your time.

{requester_block}
"""


def build_request(
    agency: str,
    state: str,
    systems: Optional[List[str]] = None,
    requester_name: str = "",
    requester_org: str = "",
    requester_email: str = "",
    requester_phone: str = "",
    address: str = "[agency mailing address]",
    fee_cap: str = "$25",
    today: Optional[_dt.date] = None,
) -> str:
    """Render a records request letter for one agency."""
    today = today or _dt.date.today()
    systems = systems or DEFAULT_SYSTEMS
    statute = STATE_STATUTES.get(
        (state or "").upper(), "applicable state public records law"
    )
    systems_block = "\n".join(f"   - {s}" for s in systems)

    requester_lines = [requester_name or "[your name]"]
    if requester_org:
        requester_lines.append(requester_org)
    if requester_email:
        requester_lines.append(requester_email)
    if requester_phone:
        requester_lines.append(requester_phone)

    return TEMPLATE.format(
        date=today.strftime("%B %d, %Y"),
        agency=agency,
        address=address,
        statute=statute,
        systems_block=systems_block,
        fee_cap=fee_cap,
        requester_block="\n".join(requester_lines),
    )
