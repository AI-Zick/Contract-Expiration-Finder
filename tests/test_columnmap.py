from pdcontracts.columnmap import map_columns


def test_maps_snake_case_portal():
    rows = [{
        "vendor_name": "Axon", "department": "Police",
        "start_date": "2024-01-01", "end_date": "2027-12-31",
        "contract_amount": "500000", "purchase_order_number": "PO-1",
    }]
    mapping = map_columns(rows[0].keys(), rows)
    assert mapping["vendor"] == "vendor_name"
    assert mapping["end_date"] == "end_date"
    assert mapping["agency"] == "department"
    assert mapping["total_value"] == "contract_amount"


def test_maps_human_titled_spreadsheet():
    rows = [{
        "Supplier": "Tyler", "Using Dept": "POLICE DEPT",
        "Effective": "01/01/2024", "Term Thru": "12/31/2029",
        "Not To Exceed Amount": "$1,200,000", "Contract No": "C-9",
    }]
    mapping = map_columns(rows[0].keys(), rows)
    assert mapping["vendor"] == "Supplier"
    assert mapping["start_date"] == "Effective"
    assert mapping["end_date"] == "Term Thru"
    assert mapping["total_value"] == "Not To Exceed Amount"


def test_maps_scope_of_work_to_description():
    rows = [{"payee": "Flock", "scope of work": "ALPR cameras", "expiration": "2028-05-31"}]
    mapping = map_columns(rows[0].keys(), rows)
    assert mapping["description"] == "scope of work"
    assert mapping["end_date"] == "expiration"


def test_value_shape_breaks_a_name_tie():
    # Both columns are plausibly "end date" by name; only one holds dates.
    rows = [
        {"end_date": "not recorded", "expiration_date": "2028-06-30"},
        {"end_date": "n/a", "expiration_date": "2029-01-15"},
        {"end_date": "", "expiration_date": "2027-03-01"},
    ]
    mapping = map_columns(rows[0].keys(), rows)
    assert mapping["end_date"] == "expiration_date"


def test_one_column_is_never_claimed_by_two_fields():
    rows = [{"amount": "1000", "vendor": "X"}]
    mapping = map_columns(rows[0].keys(), rows)
    claimed = [v for v in mapping.values()]
    assert len(claimed) == len(set(claimed))


def test_overrides_pin_a_mapping():
    rows = [{"col_a": "Axon", "col_b": "2027-01-01"}]
    mapping = map_columns(rows[0].keys(), rows, overrides={"vendor": "col_a", "end_date": "col_b"})
    assert mapping["vendor"] == "col_a"
    assert mapping["end_date"] == "col_b"


def test_unmappable_table_yields_no_false_positives():
    rows = [{"alpha": "1", "beta": "2"}]
    mapping = map_columns(rows[0].keys(), rows)
    assert "vendor" not in mapping
    assert "end_date" not in mapping
