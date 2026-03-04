#!/usr/bin/env python3

import io
import pandas as pd
from dash import html, dash_table
import dash_bootstrap_components as dbc

from gardi.core.filters import FilterType
from gardi.core.models import Line, EventType, DISTANCE_MAP, Direction


def fmt_time(t):
    """Format time in minutes to HH:MM string"""
    if t is None:
        return "--:--"
    t = int(round(t))
    return f"{t//60:02d}:{t%60:02d}"


def make_summary_card(title, items, footer=None):
    """Reusable helper to build a clean, minimal summary card."""
    return dbc.Card(
        [
            dbc.CardHeader(
                html.Strong(title, style={"fontSize": "14px", "color": "#1e293b"}),
                style={
                    "backgroundColor": "#f8fafc",
                    "borderBottom": "1px solid #e2e8f0",
                    "padding": "6px 10px",
                },
            ),
            dbc.CardBody(
                [
                    html.Ul(
                        [html.Li(i, style={"marginBottom": "4px"}) for i in items],
                        style={
                            "paddingLeft": "18px",
                            "margin": "0",
                            "fontSize": "13px",
                            "color": "#334155",
                            "listStyleType": "disc",
                        },
                    )
                ],
                style={"padding": "10px 12px"},
            ),
            (
                dbc.CardFooter(
                    footer if footer else "",
                    style={
                        "backgroundColor": "#fafafa",
                        "borderTop": "1px solid #e2e8f0",
                        "fontSize": "12px",
                        "color": "#64748b",
                        "padding": "6px 10px",
                    },
                )
                if footer
                else None
            ),
        ],
        style={
            "borderRadius": "8px",
            "border": "1px solid #e2e8f0",
            "boxShadow": "0 1px 2px rgba(0,0,0,0.04)",
            "backgroundColor": "white",
            "height": "100%",
        },
    )


class DataBuilder:
    def build_service_table_data(self, wtt):
        rows = []
        for svc in wtt.suburbanServices:
            if not svc.render or not svc.events:
                continue

            svc_id_str = ",".join(str(sid) for sid in svc.serviceId)
            svc_events = [e for e in svc.events if not e.isTerminalDeparture]
            start_time = fmt_time(svc_events[0].atTime) if svc_events else "--:--"
            end_time = fmt_time(svc_events[-1].atTime) if svc_events else "--:--"
            duration_min = int(svc_events[-1].atTime) - int(svc_events[0].atTime)

            rows.append(
                {
                    "id": svc_id_str,
                    "service_id": svc_id_str,
                    "direction": svc.direction.name if svc.direction else "?",
                    "is_ac": "AC" if svc.needsACRake else "Non-AC",
                    "line": svc.line.name if svc.line else "?",
                    "start_station": (
                        svc.initStation.name if svc.initStation else "?"
                    ),
                    "start_time": start_time,
                    "duration": duration_min,
                    "end_station": (
                        svc.finalStation.name if svc.finalStation else "?"
                    ),
                }
            )

        return rows

    def build_rake_table_data(self, wtt):
        rows = []
        for rc in wtt.rakecycles:
            if not rc.render or rc.rake is None:
                continue

            rows.append(
                {
                    "id": rc.linkName,
                    "linkname": rc.linkName,
                    "cars": rc.rake.rakeSize,
                    "is_ac": "AC" if rc.rake.isAC else "Non-AC",
                    "length_km": int(rc.lengthKm),
                    "start": rc.servicePath[0].initStation.name,
                    "end": rc.servicePath[-1].finalStation.name,
                    "duration": f"{int(rc.durationMinutes) // 60:02d}:{int(rc.durationMinutes) % 60:02d}",
                }
            )

        return rows

    def export_to_xlsx(self, wtt):
        """
        Generates a Pandas DataFrame containing the filtered services with
        columns for Direction, Line, Service ID, Stations, and Timings.
        """
        rows = []

        for svc in wtt.suburbanServices:
            if not getattr(svc, "render", True):
                continue

            dep_time = "--:--"
            arr_time = "--:--"
            if svc.events:
                dep_time = fmt_time(svc.events[0].atTime)
                arr_time = fmt_time(svc.events[-1].atTime)

            if svc.line == Line.THROUGH:
                line_str = "Fast"
            elif svc.line == Line.LOCAL:
                line_str = "Slow"
            else:
                line_str = "Unknown"

            rows.append(
                {
                    "Service ID": ", ".join(str(sid) for sid in svc.serviceId),
                    "Start Time": dep_time,
                    "Source": svc.initStation.name,
                    "Destination": svc.finalStation.name,
                    "Direction": svc.direction.name,
                    "Line": line_str,
                }
            )

        return pd.DataFrame(rows)

    def export_results_text(self, wtt, query):
        buffer = io.StringIO()

        buffer.write(f"Filter Query: {query}\n\n")

        # list rakecycle inconsistencies
        buffer.write("=== Rake Link Inconsistencies ===\n")
        if wtt.conflictingLinks:
            for el in wtt.conflictingLinks:
                buffer.write(f"Link {el[0].linkName}")
                buffer.write(f"  Summary: {el[0].serviceIds}\n")
                buffer.write(f"  WTT:     {el[1]}\n---\n")
        else:
            buffer.write("  No inconsistencies found.\n")

        if query.type == FilterType.RAKELINK:
            buffer.write("\n=== Rake Links Plotted (RakeLink Filter) ===\n")
            plotted_rcs = [rc for rc in wtt.rakecycles if rc.render]
            if plotted_rcs:
                for rc in plotted_rcs:
                    buffer.write(f"{rc}\n")
                    buffer.write(f"Services: {rc.serviceIds}\n")
            else:
                buffer.write("  No rake links matched the filter criteria.\n")

        if query.type == FilterType.SERVICE:
            buffer.write(
                "\n=== Rake Links with Rendered Services (Service Filter) ===\n"
            )
            any_rendered = False
            for rc in wtt.rakecycles:
                if not rc.render:
                    continue

                rendered_services = [svc for svc in rc.servicePath if svc.render]

                if rendered_services:
                    any_rendered = True
                    buffer.write(f"\n{rc}\n")
                    buffer.write(
                        f"  Rendered Services ({len(rendered_services)}/{len(rc.servicePath)}):\n"
                    )
                    for svc in rendered_services:
                        buffer.write(f"    {svc}\n")

            if not any_rendered:
                buffer.write("  No services matched the filter criteria.\n")

            # === Passing Through Times (sorted) ===
            if query.passingThrough:
                buffer.write(
                    "\n=== Passing Through Times (Grouped by Station, Sorted by Time) ===\n"
                )

                pt_stations = [s.upper() for s in query.passingThrough]

                rendered_services = [
                    svc
                    for svc in wtt.suburbanServices
                    if getattr(svc, "render", False)
                ]

                if not rendered_services:
                    buffer.write("  No services matched the filter criteria.\n\n")
                else:
                    st_table = {st: [] for st in pt_stations}

                    for svc in rendered_services:
                        sid = svc.serviceId[0]

                        st_times = {}
                        for ev in svc.events:
                            if not getattr(ev, "render", True):
                                continue
                            st = ev.atStation.upper()
                            st_times.setdefault(st, []).append(ev.atTime)

                        for st in pt_stations:
                            if st in st_times:
                                t = st_times[st][-1]
                                hh = int(t // 60)
                                mm = int(t % 60)
                                time_str = f"{hh:02d}:{mm:02d}"
                                st_table[st].append((sid, t, time_str))
                            else:
                                st_table[st].append((sid, None, "---"))

                    for st in pt_stations:
                        st_table[st].sort(key=lambda x: (x[1] is None, x[1]))

                    for st in pt_stations:
                        buffer.write(f"\n=== {st} ===\n")
                        for sid, t, time_str in st_table[st]:
                            buffer.write(f"   {sid:<8} {time_str}\n")

                    buffer.write("\n")

        return buffer.getvalue()

    def generate_summary_status(self, wtt, query):
        # compute stats
        rcs = [rc for rc in wtt.rakecycles if rc.render]

        total_services = 0
        ac_services = 0
        for rc in rcs:
            total_services += len(rc.servicePath)
            for svc in rc.servicePath:
                if svc.needsACRake and svc.render:
                    ac_services += 1

        total_parsed_services = len(wtt.suburbanServices)
        non_ac_services = total_services - ac_services

        total_parsed_links = len(wtt.rakecycles)
        parsing_conflicts = len(wtt.conflictingLinks)

        total_rendered_links = len(rcs)
        valid_rcs = [rc for rc in rcs if rc.lengthKm > 0]
        shortest_rcs = sorted(valid_rcs, key=lambda rc: rc.lengthKm)[:3]
        longest_rcs = sorted(valid_rcs, key=lambda rc: rc.lengthKm, reverse=True)[:3]

        svcs = [s for s in wtt.suburbanServices if s.render]
        if query.type == FilterType.SERVICE:
            total_services = len(svcs)
            non_ac_services = total_services - ac_services

        service_items = [
            f"Total Parsed services: {total_parsed_services}",
            f"Rendered Services: {total_services}",
            f"AC services: {ac_services}",
            f"Non-AC services: {non_ac_services}",
        ]

        rake_items = [
            f"Total parsed rake links: {total_parsed_links}",
            f"Parsing Conflicts: {parsing_conflicts}",
            f"Rendered Links: {total_rendered_links}",
        ]

        rake_footer = html.Div(
            [
                html.Small(
                    "Shortest: "
                    + ", ".join(
                        f"{rc.linkName} ({rc.lengthKm:.1f} km)" for rc in shortest_rcs
                    )
                ),
                html.Br(),
                html.Small(
                    "Longest: "
                    + ", ".join(
                        f"{rc.linkName} ({rc.lengthKm:.1f} km)" for rc in longest_rcs
                    )
                ),
            ]
        )

        service_card = make_summary_card("Service Summary", service_items)
        rake_card = make_summary_card(
            "Rake Link Summary", rake_items, footer=rake_footer
        )

        summary_layout = dbc.Row(
            [
                dbc.Col(service_card, width=6, style={"padding": "4px"}),
                dbc.Col(rake_card, width=6, style={"padding": "4px"}),
            ],
            className="g-1",
            style={"margin": "0"},
        )

        return html.Div(
            summary_layout,
            style={
                "margin": "0px 0px 0px 0px",
                "padding": "0px 4px",
                "borderRadius": "6px",
                "backgroundColor": "#f9fafb",
            },
        )

    def build_station_gap_summary(self, parser, query):
        """Build per-station gap summary table for station filter mode.

        Returns list of dicts with gap statistics per station, sorted by distance.
        """
        rows = []

        for station_name, events in parser.eventsByStationMap.items():
            # Collect rendered events, collapse arr+dep pairs per service to single event
            svc_times = {}  # service_id -> (time, direction, is_ac, line)
            for ev in events:
                if not ev.render:
                    continue
                if ev.atTime is None:
                    continue
                svc = ev.ofService
                if not svc.render:
                    continue
                sid = svc.serviceId[0]
                # Keep departure time if available (overrides arrival)
                if sid not in svc_times or ev.eType == EventType.DEPARTURE:
                    svc_times[sid] = (ev.atTime, svc.direction, svc.needsACRake, svc.line)

            if not svc_times:
                continue

            times_with_meta = sorted(svc_times.values(), key=lambda x: x[0])
            times = [t[0] for t in times_with_meta]
            up_count = sum(1 for t in times_with_meta if t[1] == Direction.UP)
            down_count = sum(1 for t in times_with_meta if t[1] == Direction.DOWN)

            if len(times) < 2:
                rows.append({
                    "station": station_name,
                    "dist_km": DISTANCE_MAP.get(station_name, 0),
                    "events": len(times),
                    "up": up_count,
                    "down": down_count,
                    "min_gap": "--",
                    "max_gap": "--",
                })
                continue

            gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
            min_gap = min(gaps)
            max_gap = max(gaps)

            rows.append({
                "station": station_name,
                "dist_km": DISTANCE_MAP.get(station_name, 0),
                "events": len(times),
                "up": up_count,
                "down": down_count,
                "min_gap": round(min_gap, 1),
                "max_gap": round(max_gap, 1),
            })

        rows.sort(key=lambda r: r["dist_km"])
        return rows

    def _classify_stop(self, svc, station_name):
        """Classify a service's stop at a station as Origin/Terminal/Pass/Halt."""
        if not svc.events:
            return "Pass"

        # Check origin/terminal by position in event list
        first_station = svc.events[0].atStation.upper() if svc.events[0].atStation else ""
        last_station = svc.events[-1].atStation.upper() if svc.events[-1].atStation else ""
        st_upper = station_name.upper()

        if st_upper == first_station:
            return "Origin"
        if st_upper == last_station:
            return "Terminal"

        # Collect this service's events at this station
        station_events = [
            ev for ev in svc.events
            if ev.atStation and ev.atStation.upper() == st_upper
            and ev.render and ev.atTime is not None
        ]

        if len(station_events) <= 1:
            return "Pass"

        # 2 events: check if arr/dep times differ
        times = sorted(ev.atTime for ev in station_events)
        if times[0] == times[-1]:
            return "Pass"

        halt_min = int(round(times[-1] - times[0]))
        return f"Halt ({halt_min}m)"

    def build_station_gap_detail(self, parser, station_names):
        """Build per-event detail table for one or more stations.

        Collects events from all stations, computes gaps within each station
        independently, sorts chronologically. Adds time_raw and station columns.
        Returns list of dicts with time, time_raw, station, service, direction,
        event_type, gap info, gap_bar.
        """
        if isinstance(station_names, str):
            station_names = [station_names]

        all_rows = []
        all_gap_values = []

        for station_name in station_names:
            events = parser.eventsByStationMap.get(station_name, [])

            # Collapse arr+dep per service, keep departure time for gap computation
            svc_map = {}  # sid -> (ev, svc)
            for ev in events:
                if not ev.render or ev.atTime is None:
                    continue
                svc = ev.ofService
                if not svc.render:
                    continue
                sid = svc.serviceId[0]
                if sid not in svc_map or ev.eType == EventType.DEPARTURE:
                    svc_map[sid] = (ev, svc)

            sorted_entries = sorted(svc_map.values(), key=lambda x: x[0].atTime)

            # Compute gaps within this station
            for i, (ev, svc) in enumerate(sorted_entries):
                gap_before = round(ev.atTime - sorted_entries[i - 1][0].atTime, 1) if i > 0 else "--"
                gap_after = round(sorted_entries[i + 1][0].atTime - ev.atTime, 1) if i < len(sorted_entries) - 1 else "--"

                if isinstance(gap_before, (int, float)):
                    all_gap_values.append(gap_before)
                if isinstance(gap_after, (int, float)):
                    all_gap_values.append(gap_after)

                event_type = self._classify_stop(svc, station_name)

                all_rows.append({
                    "time": fmt_time(ev.atTime),
                    "time_raw": round(ev.atTime, 2),
                    "station": station_name,
                    "service": ",".join(str(s) for s in svc.serviceId),
                    "direction": svc.direction.name if svc.direction else "?",
                    "is_ac": "AC" if svc.needsACRake else "Non-AC",
                    "line": "Fast" if svc.line == Line.THROUGH else "Slow" if svc.line == Line.LOCAL else "Semi-Fast" if svc.line == Line.SEMI_FAST else "?",
                    "event_type": event_type,
                    "gap_before": gap_before,
                    "gap_after": gap_after,
                })

        # Sort all rows chronologically
        all_rows.sort(key=lambda r: r["time_raw"])

        # Build bidirectional gap bar: ■*│ chars, 7 per side + center │
        max_gap = max(all_gap_values) if all_gap_values else 1
        half_w = 7
        for row in all_rows:
            gb = row["gap_before"]
            ga = row["gap_after"]
            gb_n = gb if isinstance(gb, (int, float)) else 0
            ga_n = ga if isinstance(ga, (int, float)) else 0

            # max_gap_val for conditional styling
            row["max_gap_val"] = max(
                gb_n if isinstance(gb, (int, float)) else 0,
                ga_n if isinstance(ga, (int, float)) else 0,
            )

            if max_gap > 0:
                left_fill = round((gb_n / max_gap) * half_w)
                right_fill = round((ga_n / max_gap) * half_w)
            else:
                left_fill = 0
                right_fill = 0

            # Left side: empty then filled, reading left-to-right toward center
            left = "\u00b7" * (half_w - left_fill) + "\u25a0" * left_fill
            # Right side: filled then empty, reading left-to-right from center
            right = "\u25a0" * right_fill + "\u00b7" * (half_w - right_fill)
            row["gap_bar"] = left + "\u2502" + right

        return all_rows

    def build_all_station_distributions(self, parser):
        """Compute gap distributions for all stations directly from parser.

        Returns dict: {station_name: {"events": int, "buckets": [bucket_rows]}}
        where each bucket row has 'bucket', 'count', 'bar'.
        Efficient: doesn't build full detail row dicts.
        """
        buckets_def = [
            ("0-2m", 0, 2),
            ("2-5m", 2, 5),
            ("5-10m", 5, 10),
            ("10-15m", 10, 15),
            ("15-20m", 15, 20),
            ("20-30m", 20, 30),
            ("30-60m", 30, 60),
            ("60m+", 60, float("inf")),
        ]

        result = {}
        for station_name, events in parser.eventsByStationMap.items():
            # Collapse arr+dep per service, keep departure time
            svc_times = {}
            for ev in events:
                if not ev.render or ev.atTime is None:
                    continue
                svc = ev.ofService
                if not svc.render:
                    continue
                sid = svc.serviceId[0]
                if sid not in svc_times or ev.eType == EventType.DEPARTURE:
                    svc_times[sid] = ev.atTime

            if len(svc_times) < 2:
                continue

            times = sorted(svc_times.values())
            gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]

            # Bucket the gaps
            counts = {b[0]: 0 for b in buckets_def}
            for g in gaps:
                for name, lo, hi in buckets_def:
                    if lo <= g < hi:
                        counts[name] += 1
                        break

            max_count = max(counts.values()) if counts else 1
            bar_width = 10
            bucket_rows = []
            for name, _, _ in buckets_def:
                c = counts[name]
                if max_count > 0:
                    filled = round((c / max_count) * bar_width)
                else:
                    filled = 0
                bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
                bucket_rows.append({"bucket": name, "count": c, "bar": bar})

            result[station_name] = {
                "events": len(svc_times),
                "buckets": bucket_rows,
            }

        return result

    def build_gap_distribution(self, detail_rows):
        """Build per-station gap distribution from detail rows.

        Returns dict: {station_name: [bucket_rows]} where each bucket row
        has 'bucket', 'count', and 'bar' (using █░ chars).
        """
        buckets = [
            ("0-2m", 0, 2),
            ("2-5m", 2, 5),
            ("5-10m", 5, 10),
            ("10-15m", 10, 15),
            ("15-20m", 15, 20),
            ("20-30m", 20, 30),
            ("30-60m", 30, 60),
            ("60m+", 60, float("inf")),
        ]

        # Group gap_before values by station
        station_gaps = {}
        for row in detail_rows:
            st = row.get("station", "?")
            gb = row.get("gap_before")
            if not isinstance(gb, (int, float)):
                continue
            station_gaps.setdefault(st, []).append(gb)

        result = {}
        for station, gaps in station_gaps.items():
            counts = {b[0]: 0 for b in buckets}
            for g in gaps:
                for name, lo, hi in buckets:
                    if lo <= g < hi:
                        counts[name] += 1
                        break

            max_count = max(counts.values()) if counts else 1
            bar_width = 10
            rows = []
            for name, _, _ in buckets:
                c = counts[name]
                if max_count > 0:
                    filled = round((c / max_count) * bar_width)
                else:
                    filled = 0
                bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
                rows.append({"bucket": name, "count": c, "bar": bar})
            result[station] = rows

        return result
