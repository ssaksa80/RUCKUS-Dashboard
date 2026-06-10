# Clients v2 — Robust Drill + Expanded Scope

Date: 2026-06-10
Status: Approved

## Problem

Client drill calls `clients/{mac}/operational/summary`, which SmartZone 7.1.1
does not serve (404 — confirmed: the live capability set has **no** per-client
GET at all; only `POST query/client` exists). The list view is also thin
(no band/channel/VLAN/user/quality).

## Design

1. **Drill from the proven list source**: `fetch_drill` walks `query/client`
   pages, matches `clientMac == entity_id` (case-insensitive), and returns:
   - `identity`: hostname, mac, ip, user, os
   - `connection`: ap, ssid, band, channel, vlan, rssi, snr
   - `usage`: rx/tx bytes, session duration (humanized from epoch-ms start)
   - `raw`: full controller row
   Tabs: Summary / Connection / Usage / Raw. MAC not found → identity with
   `note: "Client not currently connected."` (no error banner, no 404).
2. **Band derivation** `_band(row)`: from `radioType`/`radioMode`/`band`
   strings — contains "6" → "6 GHz", "5" → "5 GHz", "2.4"/"24"/"11g"/"11b" →
   "2.4 GHz", else "—".
3. **Quality derivation** `_quality(rssi)`: negative values are dBm
   (good ≥ −65, fair ≥ −75, poor < −75); positive values are SNR-like
   (good ≥ 25, fair ≥ 15, poor < 15); 0/missing → "unknown".
4. **Columns**: Host, MAC, IP, User, SSID, AP, Band, Channel, VLAN, Quality
   (status pill), RX, TX, OS. Filters: ssid, os, band, quality.
5. **KPIs**: total, band_2_4/band_5/band_6 counts, poor_signal (count),
   top_talker (hostname of max rx+tx).
6. **Diagnostic**: fetch returns `raw_rows[:2]` so the dump exposes the real
   field names for any column rendering "—".
7. All field reads are defensive `.get` with fallbacks — absent fields render
   "—", never raise.

## Testing

Mocked `query/client`: drill match + sections; not-found note; band/quality
derivations; KPI math (incl. top talker); raw_rows present. Full suite green.
