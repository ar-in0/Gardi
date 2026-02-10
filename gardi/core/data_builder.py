#!/usr/bin/env python3

import io
import pandas as pd
from dash import html, dash_table
import dash_bootstrap_components as dbc

from gardi.core.filters import FilterType
from gardi.core.models import Line


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
            start_time = fmt_time(svc.events[0].atTime) if svc.events else "--:--"

            # Find which rake link this service belongs to
            rake_link = "?"
            for rc in wtt.rakecycles:
                if svc in rc.servicePath:
                    rake_link = rc.linkName
                    break

            rows.append(
                {
                    "id": svc_id_str,
                    "service_id": svc_id_str,
                    "direction": svc.direction.name if svc.direction else "?",
                    "is_ac": "AC" if svc.needsACRake else "Non-AC",
                    "cars": svc.rakeSizeReq if svc.rakeSizeReq else "?",
                    "start_station": (
                        svc.initStation.name if svc.initStation else "?"
                    ),
                    "end_station": (
                        svc.finalStation.name if svc.finalStation else "?"
                    ),
                    "start_time": start_time,
                    "rake_link": rake_link,
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
                    "n_services": len(rc.servicePath),
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
