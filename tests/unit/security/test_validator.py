import responses

from ruckus_dashboard.security import SecurityLookupCache, validate_assets
from ruckus_dashboard.security import validator

CFG = {"RUCKUS_SECURITY_LOOKUPS": False,
       "RUCKUS_MAX_SECURITY_LOOKUPS": 12, "RUCKUS_NVD_RESULTS": 5,
       "RUCKUS_SECURITY_CACHE_SECONDS": 21600}


def _cache():
    return SecurityLookupCache(CFG["RUCKUS_SECURITY_CACHE_SECONDS"])


def test_disabled_sets_unknown_without_network():
    # No responses registered: any network call would raise.
    assets = [{"model": "R650", "firmware_version": "7.0.0", "name": "AP-1",
               "platform": "smartzone"}]
    result = validate_assets(assets, CFG, _cache())
    assert result["status"] == "disabled"
    assert result["sources"] == []
    assert assets[0]["security"]["status"] == "unknown"
    assert assets[0]["security"]["known_exploited"] == []
    assert assets[0]["security"]["known_cves"] == []


def test_cache_get_put_roundtrip_and_ttl():
    cache = SecurityLookupCache(ttl_seconds=1000)
    assert cache.get("missing") is None
    assert cache.put("k", [1, 2, 3]) == [1, 2, 3]
    assert cache.get("k") == [1, 2, 3]
    expired = SecurityLookupCache(ttl_seconds=-1)
    expired.put("k", "v")
    assert expired.get("k") is None


@responses.activate
def test_enabled_critical_on_kev_match():
    cfg = {**CFG, "RUCKUS_SECURITY_LOOKUPS": True}
    responses.add(responses.GET, validator.CISA_KEV_URL, json={
        "vulnerabilities": [{
            "cveID": "CVE-2023-0001",
            "vendorProject": "Ruckus",
            "product": "SmartZone",
            "vulnerabilityName": "Ruckus SmartZone RCE",
            "shortDescription": "ruckus smartzone bug",
            "dateAdded": "2023-01-01",
            "dueDate": "2023-02-01",
            "requiredAction": "Patch now",
        }]
    }, status=200)
    responses.add(responses.GET, validator.NVD_CVE_URL,
                  json={"vulnerabilities": []}, status=200)

    assets = [{"model": "SmartZone", "firmware_version": "5.2", "name": "SZ",
               "platform": "smartzone"}]
    result = validate_assets(assets, cfg, _cache())
    assert result["status"] in {"complete", "partial"}
    assert assets[0]["security"]["status"] == "critical"
    assert result["critical_count"] == 1


@responses.activate
def test_enabled_ok_when_no_matches():
    cfg = {**CFG, "RUCKUS_SECURITY_LOOKUPS": True}
    responses.add(responses.GET, validator.CISA_KEV_URL,
                  json={"vulnerabilities": []}, status=200)
    responses.add(responses.GET, validator.NVD_CVE_URL,
                  json={"vulnerabilities": []}, status=200)

    assets = [{"model": "R650", "firmware_version": "7.0.0", "name": "AP-1",
               "platform": "smartzone"}]
    result = validate_assets(assets, cfg, _cache())
    assert assets[0]["security"]["status"] == "ok"
    assert result["ok_count"] == 1
