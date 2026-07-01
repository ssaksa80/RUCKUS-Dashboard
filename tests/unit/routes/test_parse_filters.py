from werkzeug.datastructures import MultiDict
from ruckus_dashboard.modules._base import Filter
from ruckus_dashboard.routes.modules import _parse_filters

SELECTS = (Filter("status", "Status", "select"),)
SEARCH = (Filter("name", "Name", "search"),)
RANGE = (Filter("clients", "Clients", "range"),)
ZONE = (Filter("zone", "Zone", "select", server_filter="ZONE_ID"),)


def test_repeated_select_kept_as_list():
    args = MultiDict([("status", "online"), ("status", "flagged")])
    out = _parse_filters(args, SELECTS)
    assert out["status"] == ["online", "flagged"]


def test_single_select_is_scalar():
    args = MultiDict([("status", "online")])
    out = _parse_filters(args, SELECTS)
    assert out["status"] == "online"


def test_search_scalar():
    args = MultiDict([("name", "lobby")])
    out = _parse_filters(args, SEARCH)
    assert out["name"] == "lobby"


def test_range_min_max_packed():
    args = MultiDict([("clients__min", "5"), ("clients__max", "20")])
    out = _parse_filters(args, RANGE)
    assert out["clients"] == {"min": "5", "max": "20"}


def test_range_only_min():
    args = MultiDict([("clients__min", "5")])
    out = _parse_filters(args, RANGE)
    assert out["clients"] == {"min": "5", "max": None}


def test_range_absent_omits_key():
    out = _parse_filters(MultiDict([]), RANGE)
    assert "clients" not in out


def test_unknown_key_ignored():
    args = MultiDict([("mystery", "x")])
    out = _parse_filters(args, SELECTS)
    assert out == {}


def test_server_filter_token_collected():
    args = MultiDict([("zone", "z1")])
    out = _parse_filters(args, ZONE)
    assert out["zone"] == "z1"
    assert out["__server"] == {"ZONE_ID": "z1"}


def test_server_filter_absent_no_server_dict():
    out = _parse_filters(MultiDict([]), ZONE)
    assert "__server" not in out


def test_page_and_limit_passthrough():
    # Paging params (used by smartzone_query_body) survive even when not a filter.
    args = MultiDict([("page", "2"), ("limit", "100")])
    out = _parse_filters(args, SELECTS)
    assert out["page"] == "2"
    assert out["limit"] == "100"
