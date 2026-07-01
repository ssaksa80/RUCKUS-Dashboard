# Graph Report - .  (2026-06-29)

## Corpus Check
- 210 files · ~89,490 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1250 nodes · 2563 edges · 118 communities (93 shown, 25 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 233 edges (avg confidence: 0.79)
- Token cost: 258,430 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_CLI & Tests|CLI & Tests]]
- [[_COMMUNITY_Parallel Fetch Infra|Parallel Fetch Infra]]
- [[_COMMUNITY_Security KEVCVE Module|Security KEV/CVE Module]]
- [[_COMMUNITY_Dashboard JS Frontend|Dashboard JS Frontend]]
- [[_COMMUNITY_App Factory & JS Tests|App Factory & JS Tests]]
- [[_COMMUNITY_SmartZone Helpers|SmartZone Helpers]]
- [[_COMMUNITY_Topology JS Renderer|Topology JS Renderer]]
- [[_COMMUNITY_HTTP Client Base|HTTP Client Base]]
- [[_COMMUNITY_CSRF Protection|CSRF Protection]]
- [[_COMMUNITY_Switch Manager Client|Switch Manager Client]]
- [[_COMMUNITY_Data Dump Command|Data Dump Command]]
- [[_COMMUNITY_Session Store & Capabilities|Session Store & Capabilities]]
- [[_COMMUNITY_Template Partials|Template Partials]]
- [[_COMMUNITY_Notification Config|Notification Config]]
- [[_COMMUNITY_SmartZone Query Body|SmartZone Query Body]]
- [[_COMMUNITY_Response Envelope|Response Envelope]]
- [[_COMMUNITY_Traffic Module|Traffic Module]]
- [[_COMMUNITY_Module Registry Tests|Module Registry Tests]]
- [[_COMMUNITY_Switch Query & Topology|Switch Query & Topology]]
- [[_COMMUNITY_Warmup & Module Registry|Warmup & Module Registry]]
- [[_COMMUNITY_Test Routes New Ui|Test Routes New Ui]]
- [[_COMMUNITY_Test Notify|Test Notify]]
- [[_COMMUNITY_Allowlist|Allowlist]]
- [[_COMMUNITY_Profiles|Profiles]]
- [[_COMMUNITY_Test Base|Test Base]]
- [[_COMMUNITY_Config|Config]]
- [[_COMMUNITY_Switches|Switches]]
- [[_COMMUNITY_Cache|Cache]]
- [[_COMMUNITY_Test Ruckus One|Test Ruckus One]]
- [[_COMMUNITY_2026 06 06 Ruckus Dashboard Plan2B Wireless|2026 06 06 Ruckus Dashboard Plan2B Wireless]]
- [[_COMMUNITY_Inflight|Inflight]]
- [[_COMMUNITY_Test Connect|Test Connect]]
- [[_COMMUNITY_Clients|Clients]]
- [[_COMMUNITY_Session Store|Session Store]]
- [[_COMMUNITY_2026 06 06 Ruckus Dashboard Plan2A Warmup|2026 06 06 Ruckus Dashboard Plan2A Warmup]]
- [[_COMMUNITY_Aps|Aps]]
- [[_COMMUNITY_Wlans|Wlans]]
- [[_COMMUNITY_Logging Setup|Logging Setup]]
- [[_COMMUNITY_Firmware|Firmware]]
- [[_COMMUNITY_Mailer|Mailer]]
- [[_COMMUNITY_2026 06 05 Ruckus Dashboard Expansion Design|2026 06 05 Ruckus Dashboard Expansion Design]]
- [[_COMMUNITY_Capability Gate|Capability Gate]]
- [[_COMMUNITY_Api Explorer|Api Explorer]]
- [[_COMMUNITY_Test Clients|Test Clients]]
- [[_COMMUNITY_Test Switches|Test Switches]]
- [[_COMMUNITY_Test Topology|Test Topology]]
- [[_COMMUNITY_Scheduler|Scheduler]]
- [[_COMMUNITY_Scheduler|Scheduler]]
- [[_COMMUNITY_Stack|Stack]]
- [[_COMMUNITY_Test Switches Drill|Test Switches Drill]]
- [[_COMMUNITY_Controller|Controller]]
- [[_COMMUNITY_Poe|Poe]]
- [[_COMMUNITY_Ports|Ports]]
- [[_COMMUNITY_Rogues|Rogues]]
- [[_COMMUNITY_Switch Groups|Switch Groups]]
- [[_COMMUNITY_Test Api Explorer|Test Api Explorer]]
- [[_COMMUNITY_Test Aps|Test Aps]]
- [[_COMMUNITY_Test Wlans|Test Wlans]]
- [[_COMMUNITY_Vlans|Vlans]]
- [[_COMMUNITY_Test Notifications Api|Test Notifications Api]]
- [[_COMMUNITY_Test Controller|Test Controller]]
- [[_COMMUNITY_Test Security|Test Security]]
- [[_COMMUNITY_Excel|Excel]]
- [[_COMMUNITY_Test Base|Test Base]]
- [[_COMMUNITY_Test Topology Layout Api|Test Topology Layout Api]]
- [[_COMMUNITY_Test Alarms|Test Alarms]]
- [[_COMMUNITY_Test Zones|Test Zones]]
- [[_COMMUNITY_Test Launch|Test Launch]]
- [[_COMMUNITY_2026 06 09 Topology Map Design|2026 06 09 Topology Map Design]]
- [[_COMMUNITY_Test Firmware|Test Firmware]]
- [[_COMMUNITY_Test Poe|Test Poe]]
- [[_COMMUNITY_Test Ports|Test Ports]]
- [[_COMMUNITY_Test Rogues|Test Rogues]]
- [[_COMMUNITY_Test Stack|Test Stack]]
- [[_COMMUNITY_Test Switch Groups|Test Switch Groups]]
- [[_COMMUNITY_Test Traffic|Test Traffic]]
- [[_COMMUNITY_Test Vlans|Test Vlans]]
- [[_COMMUNITY_Warmup|Warmup]]
- [[_COMMUNITY_2026 06 09 Topology Map|2026 06 09 Topology Map]]
- [[_COMMUNITY_2026 06 10 Alerting Reporting Design|2026 06 10 Alerting Reporting Design]]
- [[_COMMUNITY_Ruckus Logo|Ruckus Logo]]
- [[_COMMUNITY_Deploy|Deploy]]
- [[_COMMUNITY_2026 06 09 Dso Overview Bar Missing Values|2026 06 09 Dso Overview Bar Missing Values]]
- [[_COMMUNITY_2026 06 05 Ruckus Dashboard Foundation|2026 06 05 Ruckus Dashboard Foundation]]
- [[_COMMUNITY_Test Backward Compat|Test Backward Compat]]
- [[_COMMUNITY_Test Overview|Test Overview]]
- [[_COMMUNITY_2026 06 10 Alerting Reporting Design|2026 06 10 Alerting Reporting Design]]
- [[_COMMUNITY_Conftest|Conftest]]
- [[_COMMUNITY_Test Install|Test Install]]
- [[_COMMUNITY_Install|Install]]
- [[_COMMUNITY_Start|Start]]
- [[_COMMUNITY_2026 06 10 Clients V2 Design|2026 06 10 Clients V2 Design]]
- [[_COMMUNITY_2026 06 09 Dso Overview Bar Missing Values Design|2026 06 09 Dso Overview Bar Missing Values Design]]
- [[_COMMUNITY_Init|Init]]
- [[_COMMUNITY_Extract Logo|Extract Logo]]
- [[_COMMUNITY_Pyproject|Pyproject]]

## God Nodes (most connected - your core abstractions)
1. `FetcherContext` - 95 edges
2. `ConnectionConfig` - 63 edges
3. `create_app()` - 51 edges
4. `CapabilityGate` - 41 edges
5. `ModuleSpec` - 41 edges
6. `smartzone_query_paged()` - 28 edges
7. `fetch_switches()` - 27 edges
8. `RuckusClientError` - 25 edges
9. `WarmupScheduler` - 25 edges
10. `request_json()` - 22 edges

## Surprising Connections (you probably didn't know these)
- `_failing_fetcher()` --calls--> `RuckusClientError`  [INFERRED]
  tests/unit/test_dump.py → RUCKUS/ruckus_dashboard/clients/base.py
- `test_authenticate_ruckus_one_happy()` --calls--> `authenticate_ruckus_one()`  [INFERRED]
  tests/unit/clients/test_ruckus_one.py → RUCKUS/ruckus_dashboard/clients/ruckus_one.py
- `test_authenticate_smartzone_happy()` --calls--> `authenticate_smartzone()`  [INFERRED]
  tests/unit/clients/test_smartzone.py → RUCKUS/ruckus_dashboard/clients/smartzone.py
- `test_connect_starts_warmup_scheduler()` --calls--> `create_app()`  [EXTRACTED]
  tests/integration/test_connect.py → RUCKUS/ruckus_dashboard/app.py
- `test_logout_cancels_warmup_scheduler()` --calls--> `create_app()`  [EXTRACTED]
  tests/integration/test_connect.py → RUCKUS/ruckus_dashboard/app.py

## Import Cycles
- 1-file cycle: `RUCKUS/ruckus_dashboard/modules/__init__.py -> RUCKUS/ruckus_dashboard/modules/__init__.py`
- 3-file cycle: `RUCKUS/ruckus_dashboard/__init__.py -> RUCKUS/ruckus_dashboard/cli.py -> RUCKUS/ruckus_dashboard/app.py -> RUCKUS/ruckus_dashboard/__init__.py`

## Hyperedges (group relationships)
- **Pages extending base.html shell** — templates_base_shell, templates_module_page, templates_notifications_page, templates_overview_page, templates_topology_page [EXTRACTED 0.95]
- **Partials rendered into the module page data area** — templates_module_page, partials_kpi_card_partial, partials_filter_chip_partial, partials_error_banner_partial, partials_status_pill_partial [INFERRED 0.75]
- **Warmup Auto-Discovery Flow (scheduler + fetcher + SSE + cache)** — plan2a_warmup_warmup_scheduler, plan2a_warmup_parallel_fetcher, plan2a_warmup_sse_stream, plan2a_warmup_warmup_status, foundation_plan_module_result_cache [EXTRACTED 0.90]
- **Topology Map Evolution (v1 graph -> v2 interactive -> v3 subtree/export)** — topology_map_topology_module, topology_v2_graph_enrichment, topology_v2_layout_persistence_api, topology_v3_refan_children, topology_v3_visible_graph [INFERRED 0.85]
- **Spec Lineage (Expansion -> Plan2 -> Plan3 designs)** — expansion_design_dso_expansion_design, plan2_design_plan2_design, plan3_frontend_dump_design_plan3_design [EXTRACTED 0.90]

## Communities (118 total, 25 thin omitted)

### Community 0 - "CLI & Tests"
Cohesion: 0.05
Nodes (50): test_cli_parses_overrides(), _args(), Integration test for the ``--dump`` headless CLI mode.  Exercises ``_run_dump_, test_dump_mode_missing_creds_returns_nonzero(), test_dump_mode_writes_valid_json(), _args(), Credential resolution for --dump: flag > env > interactive prompt.  Passwords, test_dump_form_uses_resolved_password() (+42 more)

### Community 1 - "Parallel Fetch Infra"
Cohesion: 0.07
Nodes (32): Event, ParallelFetcher, Concurrent fetcher with per-task timeout and exception capture., Run a dict of `{id: callable}` concurrently with a per-task timeout.      Retu, TaskResult, test_captures_exceptions_per_task(), test_concurrent_execution_faster_than_sequential(), test_empty_task_dict_returns_empty() (+24 more)

### Community 2 - "Security KEV/CVE Module"
Cohesion: 0.12
Nodes (38): _build_asset(), fetch(), _flatten_security(), merge(), Security module — validates the live AP inventory against CISA KEV + NVD CVE., Lift the nested ``security`` dict into flat, table-friendly columns     (the ra, summary(), Any (+30 more)

### Community 3 - "Dashboard JS Frontend"
Cohesion: 0.09
Nodes (32): activeFilters, activeViews, _applyFilters(), applyHealthState(), applyKpiFilter(), _escape(), fetchModule(), formatCell() (+24 more)

### Community 4 - "App Factory & JS Tests"
Cohesion: 0.09
Nodes (30): test_app_factory_returns_flask(), test_healthz_returns_200(), test_security_headers_present(), formatCell/KPI strip/filters must HTML-escape controller-sourced strings     (a, DSO wall mode hides the sidebar; the grid must collapse to one column or     .m, test_dashboard_js_contains_columns_filters_rowclick(), test_dashboard_js_contains_drill_rendering(), test_dashboard_js_contains_health_bar() (+22 more)

### Community 5 - "SmartZone Helpers"
Cohesion: 0.16
Nodes (32): _as_list(), _coerce_int(), _first_value(), _aggregate_ap_status(), _api_version_key(), authenticate_smartzone(), _build_patch_posture(), _build_patching_details() (+24 more)

### Community 6 - "Topology JS Renderer"
Cohesion: 0.09
Nodes (20): animateToPositions(), applySearch(), centerOn(), diffAndToast(), _esc(), fmtRate(), humanTopoBytes(), layoutGraph() (+12 more)

### Community 7 - "HTTP Client Base"
Cohesion: 0.18
Nodes (27): _extract_items(), _first_present(), _format_now(), _format_time(), _host_label(), _nested_first(), _nested_value(), _parse_datetime() (+19 more)

### Community 8 - "CSRF Protection"
Cohesion: 0.14
Nodes (22): CSRF token validator. Lifted from monolith _validate_csrf., Abort 400 if request CSRF token missing or mismatched.      Accepts the token, validate_csrf(), make_app(), test_header_token_passes(), test_mismatched_token_400(), test_missing_token_400(), test_valid_token_passes() (+14 more)

### Community 9 - "Switch Manager Client"
Cohesion: 0.13
Nodes (23): _maybe_disable_tls_warnings(), RuckusClientError, _aggregate_switch_status(), fetch_switches(), RUCKUS Switch Manager (``/switchm/api``) client.  Extracted from ``clients/sma, API bases to try for switch-manager endpoints, in priority order.      Primary, Full SmartZone query body the Switch Manager endpoints require.      A bare ``, ICX switch online/offline counts via the Switch Manager API.      Walks versio (+15 more)

### Community 10 - "Data Dump Command"
Cohesion: 0.14
Nodes (18): _dump_module(), _error_text(), Headless data dump: capture everything the dashboard collects into one JSON., Run discovery + every module fetcher + a sample drill. Returns a JSON-safe dict., Bound a redacted structure for the dump: cap recursion depth and list size., run_dump(), _safe_capabilities(), _truncate() (+10 more)

### Community 11 - "Session Store & Capabilities"
Cohesion: 0.16
Nodes (22): ConnectionConfig, In-memory connection session store with TTL-based eviction.  Holds authenticat, _safe_url(), _candidate_probes(), _capability_group(), discover_capabilities(), _discover_openapi_source(), _discover_smartzone_capabilities() (+14 more)

### Community 12 - "Template Partials"
Cohesion: 0.09
Nodes (25): entity_link.html partial, error_banner.html partial, filter_chip.html partial, freshness_strip.html partial, health_bar.html partial, kpi_card.html partial, status_pill.html partial, table_pagination.html partial (+17 more)

### Community 13 - "Notification Config"
Cohesion: 0.21
Nodes (19): display_config(), load_config(), _merged(), _path(), Notification configuration persisted in the app instance folder.  The SMTP pas, Merge an incoming (display-shaped) config and persist it.      ``incoming["smt, Shape for the UI: password masked (or empty when unset)., save_config() (+11 more)

### Community 14 - "SmartZone Query Body"
Cohesion: 0.16
Nodes (18): Build a standard SmartZone ``/query/*`` POST body.      The SmartZone public q, smartzone_query_body(), Regression: SmartZone /query/* body must be 1-indexed.  Live SmartZone 7.1.1 r, test_default_limit_is_500(), test_default_page_is_one(), test_explicit_page_preserved(), test_negative_page_coerced_to_one(), test_no_filters_key_when_no_zone() (+10 more)

### Community 15 - "Response Envelope"
Cohesion: 0.17
Nodes (16): build_envelope(), ControllerError, Unified envelope for module responses (status / data / errors)., test_complete_envelope_no_errors(), test_error_envelope_no_data(), test_partial_envelope_with_one_error(), _default_merge(), _log_upstream() (+8 more)

### Community 16 - "Traffic Module"
Cohesion: 0.19
Nodes (18): FetcherContext, fetch(), fetch_drill(), merge(), _normalize(), Switch Traffic — top switches by traffic usage module., summary(), _switch_name_map() (+10 more)

### Community 17 - "Module Registry Tests"
Cohesion: 0.13
Nodes (14): all_modules(), Contract test for per-module Column/Filter declarations.  We cannot assert tha, test_columns_have_valid_keys_and_kinds(), test_filters_have_valid_keys_and_kinds(), Guard against a module file existing but missing from the package's     import l, test_all_modules_registered(), test_all_modules_registered_in_fresh_process(), test_modules_grouped_correctly() (+6 more)

### Community 18 - "Switch Query & Topology"
Cohesion: 0.20
Nodes (18): smartzone_get(), smartzone_paged_get(), POST a switch-manager query across version + path candidates.      Tries ``pat, switch_manager_query(), _alarms_for(), _build_graph(), fetch(), _human_bytes() (+10 more)

### Community 19 - "Warmup & Module Registry"
Cohesion: 0.16
Nodes (13): WarmupScheduler — runs every applicable module fetcher once per session.  Trig, ModuleSpec contract — every dashboard module declares one., Module registry. Built modules call register() at import time., register(), fetch(), merge(), DSO Overview — tiles populated by the warmup SSE stream., summary() (+5 more)

### Community 20 - "Test Routes New Ui"
Cohesion: 0.16
Nodes (18): _authed_app_with_conn(), make_app(), App with one stored SmartZone connection + matching capability., A single module's upstream RuckusClientError must NOT 500 the request.      Re, With 2 controllers, one OK + one failing → status 'partial', data kept., test_drill_route_unauthenticated_401(), test_drill_route_unknown_module_404(), test_module_data_endpoint_unauthenticated_401() (+10 more)

### Community 21 - "Test Notify"
Cohesion: 0.14
Nodes (12): evaluate(), FakeSecrets, Unit tests for notification config, rules, mailer, scheduler due-logic, and the, Second traffic poll derives bits/s from the cumulative-byte delta., _sched(), test_alerts_due_respects_interval(), test_config_password_encrypted_masked_and_preserved(), test_poor_ap_rule_fires_for_new_aps_only() (+4 more)

### Community 22 - "Allowlist"
Cohesion: 0.20
Nodes (10): assert_host_allowed(), HostAllowList, Host allow-list / SSRF guard.  Ported from the monolith (RUCKUS/ruckus_dashboa, fake_dns(), Make hostname resolution hermetic for the allow-list tests., test_cidr_match(), test_disallowed_raises(), test_empty_list_allows_everything() (+2 more)

### Community 23 - "Profiles"
Cohesion: 0.22
Nodes (7): _format_now(), ProfileStore, Connection profiles — save/load/delete; passwords/secrets encrypted at rest., test_save_list_delete(), test_save_requires_profile_name(), Any, SecretsManager

### Community 24 - "Test Base"
Cohesion: 0.20
Nodes (12): Filter, ModuleSpec, test_filter_defaults_select_kind(), test_module_spec_accepts_columns_and_filters(), test_module_spec_columns_filters_default_empty(), test_module_spec_merge_function_attaches(), test_module_spec_minimal_valid(), test_module_spec_rejects_invalid_group() (+4 more)

### Community 25 - "Config"
Cohesion: 0.22
Nodes (13): Flask app factory. Routes registered by their own files., _bool_env(), build_config(), _float_env(), _int_env(), load_secret_key(), Config builder + env parsers. Lifted from the monolith; new flags added., _tls_verify_env() (+5 more)

### Community 26 - "Switches"
Cohesion: 0.23
Nodes (14): _api_version_fallbacks(), Switch Manager API version candidates, newest first.      The Switch Manager (, _drill_health(), _drill_ports(), fetch(), fetch_drill(), merge(), _normalize() (+6 more)

### Community 27 - "Cache"
Cohesion: 0.20
Nodes (8): ModuleResultCache, Per (connection-set, module, filters) result cache with TTL., test_different_filters_dont_collide(), test_invalidate_connection(), test_miss_returns_none(), test_put_then_get_returns_value(), test_ttl_expires(), Any

### Community 28 - "Test Ruckus One"
Cohesion: 0.18
Nodes (12): _format_host(), _safe_port(), normalize_ruckus_one_base(), normalize_smartzone_base(), test_authenticate_ruckus_one_happy(), test_normalize_region_eu(), test_normalize_region_na(), test_normalize_rejects_http() (+4 more)

### Community 29 - "2026 06 06 Ruckus Dashboard Plan2B Wireless"
Cohesion: 0.14
Nodes (14): 1354 Controller API Operations (1116 SmartZone + 238 Switch Manager), ModuleSpec Contract (one file per module), ModuleSpec Dataclass + Registry, ModuleSpec Extensions (warmup + merge fields), api-explorer warmup=False (avoid hammering 1354 ops), Access Points Module (modules/aps.py), Drill-in Route /api/modules/<slug>/<entity_id>, Per-Module File Template (fetch/summary/drill/merge) (+6 more)

### Community 30 - "Inflight"
Cohesion: 0.18
Nodes (9): InFlightDeduper, Concurrent duplicate-fetch deduplication.  Late callers that arrive while a ca, Per-cycle holder shared between the owner thread and any waiters.      Tying r, Deduplicate concurrent calls keyed by a string., _Slot, test_concurrent_calls_share_result(), test_different_keys_dont_dedupe(), test_single_call_executes_once() (+1 more)

### Community 31 - "Test Connect"
Cohesion: 0.27
Nodes (13): make_app(), Login flow: GET /, POST /connect, POST /logout.  Tests run against the real ap, GET / to seed the csrf_token in the session, return the token., seed_csrf(), test_connect_post_invalid_platform_flashes_and_redirects(), test_connect_post_missing_csrf_400(), test_connect_post_smartzone_happy(), test_connect_starts_warmup_scheduler() (+5 more)

### Community 32 - "Clients"
Cohesion: 0.25
Nodes (13): _band(), fetch(), fetch_drill(), merge(), _normalize(), _quality(), Clients — wireless client inventory.  SmartZone 7.1.1 serves no per-client GET, {zoneId: zoneName} so Site shows names, not GUIDs. Best-effort. (+5 more)

### Community 33 - "Session Store"
Cohesion: 0.27
Nodes (6): ConnectionStore, make_cfg(), test_count(), test_put_get_round_trip(), test_remove(), test_ttl_eviction()

### Community 34 - "2026 06 06 Ruckus Dashboard Plan2A Warmup"
Cohesion: 0.17
Nodes (12): Transition-only Alert Rules (evaluate prev vs current), Excel Report Builder (reports/excel.py, openpyxl), NotifyScheduler (daemon: alerts + daily report), nginx Reverse Proxy (SSE-aware), Persistent DSO Health Bar, CapabilityGate (OpenAPI op gating), ModuleResultCache, Async Warmup UX with SSE Progress Strip (+4 more)

### Community 35 - "Aps"
Cohesion: 0.27
Nodes (11): _client_rssi_by_ap(), fetch(), fetch_drill(), _filter_body(), merge(), _normalize(), Access Points — primary wireless module., Realtime per-AP average client signal (dBm) — refreshed every poll. (+3 more)

### Community 36 - "Wlans"
Cohesion: 0.27
Nodes (11): _clients_per_site(), fetch(), fetch_drill(), _group_by_site(), merge(), _normalize(), WLANs — site-wise rollup: WLANs per site + clients connected per site.  Rows a, {site key: connected clients} from query/client. Best-effort. (+3 more)

### Community 37 - "Logging Setup"
Cohesion: 0.25
Nodes (8): LogRecord, configure_logging(), _JsonLogFormatter, Structured JSON logging (rotating file + stderr), ported from the monolith.  P, Tests for ruckus_dashboard.logging_setup (Task 5)., test_configure_logging_idempotent(), test_configure_logging_writes_log_file(), test_json_formatter_emits_valid_json()

### Community 38 - "Firmware"
Cohesion: 0.33
Nodes (9): TabSpec, fetch(), _fetch_catalog(), fetch_drill(), _latest_supported(), merge(), Firmware module — per-zone AP firmware catalog + compliance posture., summary() (+1 more)

### Community 39 - "Mailer"
Cohesion: 0.27
Nodes (8): BaseException, SMTP delivery for alerts and reports.  Ported from the proven networker-dashboar, Send via the configured SMTP server. Raises SmtpDeliveryError with the     faili, _security(), send_email(), smtp_exception_detail(), SmtpDeliveryError, test_send_email_requires_host_and_recipients()

### Community 40 - "2026 06 05 Ruckus Dashboard Expansion Design"
Cohesion: 0.20
Nodes (10): RUCKUS Dashboard DSO Expansion Design (Spec), Hub + Drill-in Navigation (Overview = DSO wall), Read-only, Live-snapshots-only Decision, RUCKUS Dashboard Foundation Implementation Plan, RUCKUS Dashboard Plan 2 Design (Real Modules + Discovery + Bootstrap), Plan 2a — Auto-Discovery + Warmup Infrastructure Plan, Plan 2b — Wireless Modules End-to-End, Plan 2d — Cross-cutting Modules + Single-command Bootstrap (+2 more)

### Community 41 - "Capability Gate"
Cohesion: 0.27
Nodes (6): CapabilityGate, Module-level capability gating using discovered controller op set., test_missing_reports_unmet(), test_no_required_caps_always_satisfied(), test_satisfied_when_all_present(), test_unsatisfied_when_missing()

### Community 42 - "Api Explorer"
Cohesion: 0.38
Nodes (9): _apply_filters(), _classify(), fetch(), merge(), _normalize(), API Explorer — searchable browser over the discovered OpenAPI op set.  Reads t, summary(), _tag() (+1 more)

### Community 43 - "Test Clients"
Cohesion: 0.36
Nodes (6): _ctx(), _mock_list(), test_clients_drill_matches_mac_from_list(), test_clients_drill_not_found_is_friendly(), test_clients_fetch_normalises_and_keeps_raw_rows(), test_clients_site_resolves_guid_to_zone_name()

### Community 44 - "Test Switches"
Cohesion: 0.24
Nodes (7): _ctx(), Field mapping against the real /switch row shape (SmartZone 7.1.1)., A switch row with numOfUnits>1 (stackId null) is one stack (7.1.1 shape)., test_stack_groups_multi_unit_switch_as_stack(), test_switch_drill_lists_connected_group_members(), test_switches_fetch_returns_normalised_rows(), test_switches_normalize_real_smartzone_711_row()

### Community 46 - "Scheduler"
Cohesion: 0.22
Nodes (8): Alert rule evaluation — transition-only firing.  State dicts: ``{"aps_offline", poor_quality_aps(), Background scheduler: automated alert e-mails + the daily Excel report.  A sin, APs where ≥ratio of their connected clients report poor quality.      min_clie, state_from_data(), test_poor_quality_aps_threshold(), test_state_from_data_counts(), Any

### Community 48 - "Stack"
Cohesion: 0.33
Nodes (8): fetch(), fetch_drill(), _group_by_stack(), merge(), ICX Stack — switch stack topology derived from switch/view/details., Identify ICX stacks from the switch list.      SmartZone 7.1.1 reports a stack, summary(), Any

### Community 49 - "Test Switches Drill"
Cohesion: 0.47
Nodes (7): _add_health(), _add_ports(), _add_switch_list(), _ctx(), test_fetch_drill_never_raises_on_total_failure(), test_fetch_drill_ports_400_yields_empty_no_raise(), test_fetch_drill_returns_identity_ports_health()

### Community 50 - "Controller"
Cohesion: 0.32
Nodes (7): Column, fetch(), merge(), Controller — SmartZone cluster + devices summary (singleton view).  7.1.1 ``cl, summary(), test_column_defaults_text_kind(), Any

### Community 51 - "Poe"
Cohesion: 0.39
Nodes (7): fetch(), fetch_drill(), merge(), _normalize(), Switch PoE — power-over-Ethernet budget per switch.  SmartZone 7.1.1's ``traff, summary(), Any

### Community 52 - "Ports"
Cohesion: 0.39
Nodes (7): fetch(), fetch_drill(), merge(), _normalize(), Switch Ports — per-switch port utilisation summary.  SmartZone 7.1.1 does not, summary(), Any

### Community 53 - "Rogues"
Cohesion: 0.39
Nodes (7): fetch(), fetch_drill(), merge(), _normalize(), Rogues — SmartZone rogue AP inventory with classification summary., summary(), Any

### Community 54 - "Switch Groups"
Cohesion: 0.36
Nodes (6): fetch(), fetch_drill(), merge(), Switch Groups — Switch Manager group hierarchy module., summary(), Any

### Community 55 - "Test Api Explorer"
Cohesion: 0.39
Nodes (5): _ctx(), test_api_explorer_filter_by_search(), test_api_explorer_filter_by_source(), test_api_explorer_lists_discovered_ops(), test_api_explorer_source_classification()

### Community 56 - "Test Aps"
Cohesion: 0.32
Nodes (4): _ctx(), 800 APs are fetched across two pages, not capped at 500., test_aps_fetch_returns_normalised_rows(), test_aps_paginates_beyond_500()

### Community 57 - "Test Wlans"
Cohesion: 0.39
Nodes (4): _ctx(), _mock(), test_wlans_grouped_per_site_with_client_counts(), test_wlans_site_drill_lists_site_wlans()

### Community 58 - "Vlans"
Cohesion: 0.39
Nodes (7): fetch(), fetch_drill(), _group_by_vlan(), merge(), VLANs — VLAN inventory and member-switch tallies module., summary(), Any

### Community 59 - "Test Notifications Api"
Cohesion: 0.62
Nodes (6): _app(), _login(), test_notifications_api_requires_auth(), test_notifications_config_roundtrip_masks_password(), test_notifications_page_renders(), test_test_email_route_uses_mailer()

### Community 62 - "Excel"
Cohesion: 0.38
Nodes (6): test_build_report_loads_and_has_sheets_and_charts(), _autofit(), build_report(), _header(), Daily Excel report — KPI overview + per-domain sheets with charts.  ``build_re, Any

### Community 63 - "Test Base"
Cohesion: 0.47
Nodes (5): Issue an HTTP request and decode JSON, wrapping errors as RuckusClientError., request_json(), test_redact_password_in_error_debug(), test_request_json_4xx_raises(), test_request_json_happy()

### Community 65 - "Test Topology Layout Api"
Cohesion: 0.67
Nodes (5): _app(), _login(), test_layout_rejects_garbage_and_missing_csrf(), test_layout_requires_auth(), test_layout_roundtrip_and_reset()

### Community 68 - "Test Launch"
Cohesion: 0.40
Nodes (5): End-to-end smoke: launch CLI, hit /healthz over self-signed HTTPS., Boot CLI, hit /api/warmup/status — expect 401 (proves blueprint registered)., test_app_boots_and_serves_healthz(), test_warmup_status_endpoint_reachable_when_unauthenticated(), _wait_port()

### Community 70 - "2026 06 09 Topology Map Design"
Cohesion: 0.33
Nodes (6): Topology Map Tab Design, Topology Map Tab Implementation Plan, Topology v2 Design (Interactive Map), Topology v2 Implementation Plan, Topology v3 Design (Subtree Drag, Collapse, Export), Topology v3 Implementation Plan

### Community 79 - "Warmup"
Cohesion: 0.50
Nodes (3): Warmup observability endpoints (SSE + sync status)., _serialise_status(), status()

### Community 80 - "2026 06 09 Topology Map"
Cohesion: 0.40
Nodes (5): Logical Hierarchy (not physical L2) Decision, layoutGraph (deterministic radial tier layout), Zero-Dependency SVG Renderer (topology.js), refanChildren (subtree re-fan on drop), visibleGraph (group collapse visibility filter)

### Community 81 - "2026 06 10 Alerting Reporting Design"
Cohesion: 0.50
Nodes (4): Encrypted SMTP Password (reuses Fernet secret-key), notify/ Package (config + mailer + rules + scheduler), Instance Folder Backup (cert/key/secret/profiles), SecretsManager (Fernet + DPAPI)

### Community 82 - "Ruckus Logo"
Cohesion: 0.50
Nodes (4): RUCKUS Logo Brandmark, CommScope Parent Brand Endorsement, RUCKUS Dashboard Branding Asset, RUCKUS Dog Mascot Icon

### Community 83 - "Deploy"
Cohesion: 0.50
Nodes (4): RUCKUS DSO Dashboard Deployment Guide, NSSM Windows Service (Windows deployment), systemd Service Unit (Linux deployment), One-command Install/Start Scripts (Unix + Windows)

### Community 84 - "2026 06 09 Dso Overview Bar Missing Values"
Cohesion: 0.50
Nodes (4): Alarms Summary Derived From List Rows, Evidence-driven Field Mapping (no API field-name guessing), Redacted raw_sample per Module (field-mapping diagnostic), Data Dump Command (--dump, run_dump)

### Community 85 - "2026 06 05 Ruckus Dashboard Foundation"
Cohesion: 0.50
Nodes (4): Backward-Compat Shim (ruckus_dashboard.py), HostAllowList SSRF Guard, RUCKUS_ENABLE_NEW_UI Feature Flag, Monolith-to-Package Refactor (lift-and-shift)

### Community 89 - "2026 06 10 Alerting Reporting Design"
Cohesion: 0.67
Nodes (3): Alert Notifications + Smart Excel Reporting Design, Clients v2 + Alerting/Reporting Plan, Clients v2 — Robust Drill + Expanded Scope Design

## Knowledge Gaps
- **62 isolated node(s):** `ruckus_dashboard`, `moduleState`, `moduleSpecs`, `activeFilters`, `lastItems` (+57 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `FetcherContext` connect `Traffic Module` to `Parallel Fetch Infra`, `Security KEV/CVE Module`, `Data Dump Command`, `Notification Config`, `SmartZone Query Body`, `Response Envelope`, `Switch Query & Topology`, `Warmup & Module Registry`, `Test Notify`, `Switches`, `Clients`, `Aps`, `Wlans`, `Firmware`, `Api Explorer`, `Test Clients`, `Test Switches`, `Test Topology`, `Scheduler`, `Stack`, `Test Switches Drill`, `Controller`, `Poe`, `Ports`, `Rogues`, `Switch Groups`, `Test Api Explorer`, `Test Aps`, `Test Wlans`, `Vlans`, `Test Controller`, `Test Security`, `Test Alarms`, `Test Zones`, `Test Firmware`, `Test Poe`, `Test Ports`, `Test Rogues`, `Test Stack`, `Test Switch Groups`, `Test Traffic`, `Test Vlans`, `Test Overview`?**
  _High betweenness centrality (0.174) - this node is a cross-community bridge._
- **Why does `ConnectionConfig` connect `Session Store & Capabilities` to `SmartZone Helpers`, `HTTP Client Base`, `Switch Manager Client`, `Switch Query & Topology`, `Test Routes New Ui`, `Test Notify`, `Test Ruckus One`, `Test Connect`, `Session Store`, `Test Clients`, `Test Switches`, `Test Topology`, `Test Switches Drill`, `Test Aps`, `Test Wlans`, `Test Controller`, `Test Security`, `Test Topology Layout Api`, `Test Alarms`, `Test Zones`, `Test Firmware`, `Test Poe`, `Test Ports`, `Test Rogues`, `Test Stack`, `Test Switch Groups`, `Test Traffic`, `Test Vlans`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `create_app()` connect `App Factory & JS Tests` to `CLI & Tests`, `Test Topology Layout Api`, `Parallel Fetch Infra`, `Session Store`, `Logging Setup`, `CSRF Protection`, `Cache`, `Scheduler`, `Test Routes New Ui`, `Allowlist`, `Profiles`, `Config`, `Test Notifications Api`, `Inflight`, `Test Connect`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `FetcherContext` (e.g. with `_ctx()` and `_ctx()`) actually correct?**
  _`FetcherContext` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `ConnectionConfig` (e.g. with `make_cfg()` and `test_fetch_inventory_uses_query_ap()`) actually correct?**
  _`ConnectionConfig` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Are the 28 inferred relationships involving `CapabilityGate` (e.g. with `test_missing_reports_unmet()` and `test_no_required_caps_always_satisfied()`) actually correct?**
  _`CapabilityGate` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `ModuleSpec` (e.g. with `FakeConn` and `make_spec()`) actually correct?**
  _`ModuleSpec` has 13 INFERRED edges - model-reasoned connections that need verification._