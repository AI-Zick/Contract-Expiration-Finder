"""SQLite persistence.

Kept deliberately simple: two tables plus a collection log. Contracts are keyed
by fingerprint so re-running a collection updates rather than duplicates, and
so the same contract found in two different portals collapses into one row.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import Agency, Contract

SCHEMA = """
CREATE TABLE IF NOT EXISTS agencies (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    state TEXT,
    city TEXT,
    county TEXT,
    ori TEXT,
    agency_type TEXT,
    sworn_officers INTEGER,
    population_served INTEGER,
    fiscal_year_start_month INTEGER,
    website TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS contracts (
    fingerprint TEXT PRIMARY KEY,
    agency_key TEXT,
    agency_name TEXT NOT NULL,
    state TEXT,
    vendor_raw TEXT,
    vendor_canonical TEXT,
    description TEXT,
    start_date TEXT,
    end_date TEXT,
    renewal_options INTEGER,
    auto_renew INTEGER,
    total_value REAL,
    annual_value REAL,
    category TEXT,
    is_software INTEGER,
    classification_confidence REAL,
    contract_number TEXT,
    source TEXT,
    source_url TEXT,
    source_dataset TEXT,
    retrieved_at TEXT,
    data_confidence REAL,
    raw TEXT
);

CREATE INDEX IF NOT EXISTS idx_contracts_end ON contracts(end_date);
CREATE INDEX IF NOT EXISTS idx_contracts_cat ON contracts(category);
CREATE INDEX IF NOT EXISTS idx_contracts_state ON contracts(state);
CREATE INDEX IF NOT EXISTS idx_contracts_agency ON contracts(agency_key);

CREATE TABLE IF NOT EXISTS collection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT,
    dataset TEXT,
    ran_at TEXT,
    fetched INTEGER,
    kept INTEGER,
    status TEXT,
    message TEXT
);
"""

CONTRACT_COLUMNS = [
    "fingerprint", "agency_key", "agency_name", "state", "vendor_raw",
    "vendor_canonical", "description", "start_date", "end_date",
    "renewal_options", "auto_renew", "total_value", "annual_value",
    "category", "is_software", "classification_confidence", "contract_number",
    "source", "source_url", "source_dataset", "retrieved_at",
    "data_confidence", "raw",
]


class Store:
    def __init__(self, path: str = "pdcontracts.sqlite"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- agencies ---------------------------------------------------------

    def upsert_agency(self, agency: Agency) -> None:
        d = agency.to_dict()
        d["key"] = agency.key
        cols = ["key"] + [c for c in d if c != "key"]
        placeholders = ",".join("?" for _ in cols)
        self.conn.execute(
            f"INSERT INTO agencies ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(key) DO UPDATE SET "
            + ",".join(f"{c}=COALESCE(excluded.{c},{c})" for c in cols if c != "key"),
            [d[c] for c in cols],
        )
        self.conn.commit()

    def get_agencies(self) -> Dict[str, Agency]:
        rows = self.conn.execute("SELECT * FROM agencies").fetchall()
        out: Dict[str, Agency] = {}
        for row in rows:
            d = dict(row)
            key = d.pop("key")
            out[key] = Agency.from_dict(d)
        return out

    # --- contracts --------------------------------------------------------

    def upsert_contracts(self, contracts: Iterable[Contract]) -> int:
        count = 0
        for contract in contracts:
            d = contract.to_dict()
            d["fingerprint"] = contract.fingerprint
            d["auto_renew"] = None if d["auto_renew"] is None else int(d["auto_renew"])
            d["is_software"] = None if d["is_software"] is None else int(d["is_software"])
            values = [d.get(c) for c in CONTRACT_COLUMNS]
            placeholders = ",".join("?" for _ in CONTRACT_COLUMNS)
            # COALESCE keeps a value already learned from a richer source when
            # the incoming record leaves that field blank.
            updates = ",".join(
                f"{c}=COALESCE(excluded.{c},{c})"
                for c in CONTRACT_COLUMNS
                if c != "fingerprint"
            )
            self.conn.execute(
                f"INSERT INTO contracts ({','.join(CONTRACT_COLUMNS)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT(fingerprint) DO UPDATE SET {updates}",
                values,
            )
            count += 1
        self.conn.commit()
        return count

    def contracts(
        self,
        states: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        software_only: bool = True,
        min_confidence: float = 0.0,
        expiring_before: Optional[_dt.date] = None,
        vendor: Optional[str] = None,
    ) -> List[Contract]:
        sql = "SELECT * FROM contracts WHERE 1=1"
        params: List = []
        if software_only:
            sql += " AND (is_software IS NULL OR is_software = 1)"
        if states:
            sql += f" AND state IN ({','.join('?' for _ in states)})"
            params += [s.upper() for s in states]
        if categories:
            sql += f" AND category IN ({','.join('?' for _ in categories)})"
            params += categories
        if min_confidence:
            sql += " AND classification_confidence >= ?"
            params.append(min_confidence)
        if expiring_before:
            sql += " AND end_date IS NOT NULL AND end_date <= ?"
            params.append(expiring_before.isoformat())
        if vendor:
            sql += " AND vendor_canonical LIKE ?"
            params.append(f"%{vendor}%")
        rows = self.conn.execute(sql, params).fetchall()
        return [Contract.from_dict(dict(r)) for r in rows]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]

    # --- logging ----------------------------------------------------------

    def log_collection(
        self, source: str, dataset: str, fetched: int, kept: int,
        status: str, message: str = "",
    ) -> None:
        self.conn.execute(
            "INSERT INTO collection_log (source,dataset,ran_at,fetched,kept,status,message) "
            "VALUES (?,?,?,?,?,?,?)",
            (source, dataset, _dt.datetime.now().isoformat(timespec="seconds"),
             fetched, kept, status, message),
        )
        self.conn.commit()

    def collection_log(self, limit: int = 50) -> List[dict]:
        rows = self.conn.execute(
            "SELECT * FROM collection_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        cur = self.conn.execute(
            "SELECT state, COUNT(*) n FROM contracts GROUP BY state ORDER BY n DESC"
        )
        by_state = {r["state"] or "?": r["n"] for r in cur.fetchall()}
        cur = self.conn.execute(
            "SELECT category, COUNT(*) n FROM contracts WHERE category != '' "
            "GROUP BY category ORDER BY n DESC"
        )
        by_category = {r["category"]: r["n"] for r in cur.fetchall()}
        cur = self.conn.execute(
            "SELECT source, COUNT(*) n FROM contracts GROUP BY source ORDER BY n DESC"
        )
        by_source = {r["source"] or "?": r["n"] for r in cur.fetchall()}
        with_end = self.conn.execute(
            "SELECT COUNT(*) FROM contracts WHERE end_date IS NOT NULL AND end_date != ''"
        ).fetchone()[0]
        return {
            "total": self.count(),
            "with_expiration": with_end,
            "agencies": self.conn.execute("SELECT COUNT(*) FROM agencies").fetchone()[0],
            "by_state": by_state,
            "by_category": by_category,
            "by_source": by_source,
        }
