"""Asset security validation against public CISA KEV + NVD CVE feeds.

Ported from the original monolith (Claude_Projects @ 26d5e91,
RUCKUS/ruckus_dashboard.py ~lines 358-730). Honors
``config["RUCKUS_SECURITY_LOOKUPS"]``: when False, validation short-circuits
to a "disabled" result and performs NO network calls.
"""
from __future__ import annotations

import time
from threading import RLock
from typing import Any
from urllib.parse import urlencode

import requests

CISA_KEV_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/"
    "known_exploited_vulnerabilities.json"
)
CISA_KEV_CATALOG_URL = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
NVD_CVE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_DETAIL_URL = "https://nvd.nist.gov/vuln/detail"


class SecurityLookupCache:
    """TTL cache for KEV/NVD feed responses, shared across asset lookups."""

    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self._entries: dict[str, tuple[float, Any]] = {}
        self._lock = RLock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            created_at, value = entry
            if time.time() - created_at > self.ttl_seconds:
                self._entries.pop(key, None)
                return None
            return value

    def put(self, key: str, value: Any) -> Any:
        with self._lock:
            self._entries[key] = (time.time(), value)
        return value


def validate_assets(
    assets: list[dict[str, Any]],
    config: dict[str, Any],
    cache: SecurityLookupCache,
) -> dict[str, Any]:
    if not config["RUCKUS_SECURITY_LOOKUPS"]:
        for asset in assets:
            asset["security"] = _security_result(
                "unknown", "Security lookups are disabled by configuration.", [], []
            )
        return {
            "status": "disabled",
            "generated_at": _format_now(),
            "sources": [],
            "message": "Security lookups are disabled.",
        }

    kev_entries, kev_error = _fetch_cisa_kev(cache)
    nvd_budget = int(config["RUCKUS_MAX_SECURITY_LOOKUPS"])
    nvd_errors: list[str] = []
    nvd_by_query: dict[str, list[dict[str, Any]]] = {}

    for asset in assets:
        kev_matches = _match_kev(asset, kev_entries)
        nvd_matches: list[dict[str, Any]] = []
        query = _asset_lookup_query(asset)
        if query in nvd_by_query:
            nvd_matches = nvd_by_query[query]
        elif nvd_budget > 0:
            nvd_budget -= 1
            nvd_matches, nvd_error = _fetch_nvd_matches(asset, config, cache)
            nvd_by_query[query] = nvd_matches
            if nvd_error:
                nvd_errors.append(nvd_error)

        status = _asset_security_status(asset, kev_matches, nvd_matches)
        asset["security"] = _security_result(
            status,
            _security_summary(status, kev_matches, nvd_matches),
            kev_matches,
            nvd_matches,
        )

    critical = sum(1 for asset in assets if asset["security"]["status"] == "critical")
    watch = sum(1 for asset in assets if asset["security"]["status"] == "watch")
    ok = sum(1 for asset in assets if asset["security"]["status"] == "ok")
    errors = [error for error in [kev_error, *nvd_errors] if error]

    return {
        "status": "complete" if not errors else "partial",
        "generated_at": _format_now(),
        "sources": ["CISA KEV", "NVD CVE 2.0"],
        "critical_count": critical,
        "watch_count": watch,
        "ok_count": ok,
        "message": (
            "Validated against public CISA KEV and NVD feeds."
            if not errors
            else "Validation completed with one or more feed lookup errors."
        ),
        "errors": errors[:5],
    }


def _fetch_cisa_kev(cache: SecurityLookupCache) -> tuple[list[dict[str, Any]], str]:
    cached = cache.get("cisa-kev")
    if cached is not None:
        return cached, ""
    try:
        response = requests.get(CISA_KEV_URL, timeout=20)
        response.raise_for_status()
        payload = response.json()
        entries = [
            item
            for item in payload.get("vulnerabilities", [])
            if _looks_ruckus_related(item)
        ]
        return cache.put("cisa-kev", entries), ""
    except (requests.RequestException, ValueError) as exc:
        return [], f"CISA KEV lookup failed: {exc}"


def _fetch_nvd_matches(
    asset: dict[str, Any],
    config: dict[str, Any],
    cache: SecurityLookupCache,
) -> tuple[list[dict[str, Any]], str]:
    query = _asset_lookup_query(asset)
    if len(query.strip()) <= len("Ruckus"):
        return [], ""
    cache_key = f"nvd:{query.lower()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached, ""
    params = {
        "keywordSearch": query,
        "resultsPerPage": max(1, int(config["RUCKUS_NVD_RESULTS"])),
    }
    try:
        response = requests.get(
            f"{NVD_CVE_URL}?{urlencode(params)}",
            timeout=20,
            headers={"User-Agent": "ruckus-noc-dashboard/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        matches = []
        for vulnerability in payload.get("vulnerabilities", []):
            cve = vulnerability.get("cve", {})
            descriptions = cve.get("descriptions", [])
            description = next(
                (item.get("value", "") for item in descriptions if item.get("lang") == "en"),
                "",
            )
            if not _text_mentions_asset(description, asset):
                continue
            cve_id = cve.get("id")
            matches.append(
                {
                    "id": cve_id,
                    "url": f"{NVD_DETAIL_URL}/{cve_id}" if cve_id else NVD_DETAIL_URL,
                    "published": cve.get("published"),
                    "last_modified": cve.get("lastModified"),
                    "severity": _severity(cve),
                    "score": _cvss_score(cve),
                    "description": description[:320],
                }
            )
        return cache.put(cache_key, matches), ""
    except (requests.RequestException, ValueError) as exc:
        return [], f"NVD lookup failed for {query}: {exc}"


def _match_kev(asset: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches = []
    asset_text = _asset_text(asset)
    for entry in entries:
        entry_text = " ".join(
            str(entry.get(key, ""))
            for key in (
                "vendorProject",
                "product",
                "vulnerabilityName",
                "shortDescription",
                "knownRansomwareCampaignUse",
            )
        ).lower()
        if "ruckus" not in entry_text and "commscope" not in entry_text:
            continue
        if _loose_product_match(asset_text, entry_text):
            matches.append(
                {
                    "id": entry.get("cveID"),
                    "url": (
                        f"{NVD_DETAIL_URL}/{entry.get('cveID')}"
                        if entry.get("cveID")
                        else CISA_KEV_CATALOG_URL
                    ),
                    "catalog_url": CISA_KEV_CATALOG_URL,
                    "product": entry.get("product"),
                    "title": entry.get("vulnerabilityName"),
                    "date_added": entry.get("dateAdded"),
                    "due_date": entry.get("dueDate"),
                    "required_action": entry.get("requiredAction"),
                }
            )
    return matches[:5]


def _asset_security_status(
    asset: dict[str, Any],
    kev_matches: list[dict[str, Any]],
    nvd_matches: list[dict[str, Any]],
) -> str:
    patch_status = str(asset.get("patch", {}).get("status") or "")
    if kev_matches:
        return "critical"
    if nvd_matches or patch_status in {"update_available", "unsupported"}:
        return "watch"
    if str(asset.get("firmware_version") or ""):
        return "ok"
    return "unknown"


def _security_summary(
    status: str,
    kev_matches: list[dict[str, Any]],
    nvd_matches: list[dict[str, Any]],
) -> str:
    if status == "critical":
        return "Known exploited vulnerability match found in public CISA KEV data."
    if status == "watch" and nvd_matches:
        return "Public CVE references found; review vendor advisory and patch plan."
    if status == "watch":
        return "Firmware patch review recommended based on catalog posture."
    if status == "ok":
        return "No public KEV/CVE match found at validation time."
    return "Validation could not be completed for this asset."


def _security_result(
    status: str,
    summary: str,
    kev_matches: list[dict[str, Any]],
    nvd_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    cve_links = _cve_links(kev_matches, nvd_matches)
    return {
        "status": status,
        "summary": summary,
        "zero_day_validation": (
            "No public active-exploitation match found"
            if not kev_matches
            else "Known exploited vulnerability requires immediate review"
        ),
        "zero_day_patch": _zero_day_patch_summary(kev_matches, nvd_matches),
        "cve_details": cve_links,
        "known_exploited": kev_matches,
        "known_cves": nvd_matches,
    }


def _looks_ruckus_related(entry: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in entry.values()).lower()
    return "ruckus" in text or "commscope" in text


def _text_mentions_asset(text: str, asset: dict[str, Any]) -> bool:
    lowered = text.lower()
    if "ruckus" not in lowered and "commscope" not in lowered:
        return False
    model = str(asset.get("model") or "").lower()
    firmware = str(asset.get("firmware_version") or "").lower()
    platform = str(asset.get("platform") or "").lower()
    return any(value and value in lowered for value in [model, firmware, platform])


def _loose_product_match(asset_text: str, entry_text: str) -> bool:
    product_words = {"smartzone", "zonedirector", "zoneflex", "unleashed", "ruckus one"}
    if any(word in asset_text and word in entry_text for word in product_words):
        return True
    model_tokens = {
        token
        for token in asset_text.replace("-", " ").replace("_", " ").split()
        if len(token) >= 3 and token[0] in {"r", "t", "h"} and token[1:].isdigit()
    }
    if model_tokens and any(token in entry_text for token in model_tokens):
        return True
    return False


def _asset_text(asset: dict[str, Any]) -> str:
    return " ".join(
        str(asset.get(key, "")) for key in ("model", "firmware_version", "name", "site")
    ).lower()


def _asset_lookup_query(asset: dict[str, Any]) -> str:
    model = str(asset.get("model") or "").strip()
    firmware = str(asset.get("firmware_version") or "").strip()
    usable_parts = [
        part
        for part in [model, firmware]
        if part and part.lower() not in {"unknown", "not reported"}
    ]
    return " ".join(["Ruckus", *usable_parts])


def _severity(cve: dict[str, Any]) -> str:
    metrics = cve.get("metrics", {})
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        values = metrics.get(key)
        if isinstance(values, list) and values:
            cvss_data = values[0].get("cvssData", {})
            severity = values[0].get("baseSeverity") or cvss_data.get("baseSeverity")
            if severity:
                return str(severity)
    return ""


def _cvss_score(cve: dict[str, Any]) -> float | None:
    metrics = cve.get("metrics", {})
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        values = metrics.get(key)
        if isinstance(values, list) and values:
            score = values[0].get("cvssData", {}).get("baseScore")
            if score is not None:
                return score
    return None


def _cve_links(
    kev_matches: list[dict[str, Any]],
    nvd_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    links = []
    seen = set()
    for match in [*kev_matches, *nvd_matches]:
        cve_id = match.get("id")
        if not cve_id or cve_id in seen:
            continue
        seen.add(cve_id)
        links.append(
            {
                "id": cve_id,
                "url": match.get("url") or f"{NVD_DETAIL_URL}/{cve_id}",
                "source": "CISA KEV" if match in kev_matches else "NVD",
                "severity": match.get("severity", ""),
                "score": match.get("score"),
                "published": match.get("published") or match.get("date_added") or "",
                "summary": match.get("title") or match.get("description") or "",
            }
        )
    return links


def _zero_day_patch_summary(
    kev_matches: list[dict[str, Any]],
    nvd_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    if kev_matches:
        due_dates = [m.get("due_date") for m in kev_matches if m.get("due_date")]
        actions = [m.get("required_action") for m in kev_matches if m.get("required_action")]
        return {
            "status": "required",
            "summary": "Known exploited vulnerability patch/remediation required.",
            "due_date": ", ".join(due_dates),
            "action": actions[0] if actions else "Apply vendor mitigation or update.",
            "links": _cve_links(kev_matches, []),
        }
    if nvd_matches:
        return {
            "status": "review",
            "summary": "CVE references found; review RUCKUS advisory and firmware patch.",
            "due_date": "",
            "action": "Validate affected firmware and apply vendor-recommended patch.",
            "links": _cve_links([], nvd_matches),
        }
    return {
        "status": "none",
        "summary": "No public zero-day patch action found.",
        "due_date": "",
        "action": "",
        "links": [],
    }


def _format_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
