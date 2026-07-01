"""Regression: SmartZone /query/* body must be 1-indexed.

Live SmartZone 7.1.1 rejects page=0 with HTTP 400
'["page"] numeric instance is lower than the required minimum (minimum: 1, found: 0)'.
"""
from ruckus_dashboard.clients.smartzone import smartzone_query_body


def test_default_page_is_one():
    assert smartzone_query_body()["page"] == 1


def test_page_zero_coerced_to_one():
    assert smartzone_query_body({"page": 0})["page"] == 1


def test_negative_page_coerced_to_one():
    assert smartzone_query_body({"page": -3})["page"] == 1


def test_explicit_page_preserved():
    assert smartzone_query_body({"page": 4})["page"] == 4


def test_default_limit_is_500():
    assert smartzone_query_body()["limit"] == 500


def test_zone_filter_translated():
    body = smartzone_query_body({"zone": "z1"})
    assert body["filters"] == [{"type": "ZONE_ID", "value": "z1"}]


def test_no_filters_key_when_no_zone():
    assert "filters" not in smartzone_query_body()


def test_server_filter_token_maps_into_body():
    body = smartzone_query_body({"__server": {"ZONE_ID": "z9"}})
    assert body["filters"] == [{"type": "ZONE_ID", "value": "z9"}]


def test_multiple_server_filter_tokens_accumulate():
    body = smartzone_query_body({"__server": {"ZONE_ID": "z1", "AP_GROUP_ID": "g2"}})
    assert {"type": "ZONE_ID", "value": "z1"} in body["filters"]
    assert {"type": "AP_GROUP_ID", "value": "g2"} in body["filters"]
    assert len(body["filters"]) == 2


def test_empty_server_filter_dict_omits_filters():
    assert "filters" not in smartzone_query_body({"__server": {}})


def test_legacy_zone_shortcut_still_works():
    body = smartzone_query_body({"zone": "z1"})
    assert body["filters"] == [{"type": "ZONE_ID", "value": "z1"}]
