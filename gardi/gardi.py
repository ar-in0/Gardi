#!/usr/bin/env python3

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc

from gardi.core.parser import TimeTableParser
from gardi.core.filters import FilterType, FilterQuery, FilterEngine
from gardi.core.graph_builder import GraphBuilder
from gardi.core.data_builder import DataBuilder, fmt_time, make_summary_card
from gardi.core.rake_operations import RakeOperations
from gardi.core.csv_builder import CsvBuilder
from gardi.ui import build_service_row


class Gardi:
    def __init__(self):
        self.parser = None
        self.wttContents = None
        self.summaryContents = None
        self.wttFileName = None
        self.summaryFileName = None

        self.linkTimingsCreated = False
        self.converted_links = []
        self._cached_report = None
        self._cached_report_links = None

        self.query = FilterQuery()
        self.query.type = FilterType.RAKELINK

        self.filterStates = {
            FilterType.RAKELINK: {},
            FilterType.SERVICE: {},
            FilterType.STATION: {},
        }

        # engines
        self.filter_engine = FilterEngine()
        self.graph_builder = GraphBuilder()
        self.data_builder = DataBuilder()
        self.rake_ops = RakeOperations()
        self.csv_builder = CsvBuilder()

    def initialize_parser(self, wtt_file_obj):
        """Parse WTT, register stations, return station options."""
        self.parser = TimeTableParser()
        self.parser.xlsxToDfFromFileObj(wtt_file_obj)
        self.parser.registerStations()

        stations = [s for s in self.parser.wtt.stations]
        options = [{"label": s, "value": s} for s in stations]
        return options

    def initialize_backend(self, summary_file_obj):
        """Parse summary, register services, isolate suburban."""
        self.parser.wtt.upServices.clear()
        self.parser.wtt.downServices.clear()
        self.parser.wtt.rakecycles.clear()
        self.parser.wtt.allCyclesWtt.clear()
        self.parser.eventsByStationMap.clear()
        self.linkTimingsCreated = False

        self.parser.registerServices()
        self.parser.parseWttSummaryFromFileObj(summary_file_obj)
        self.parser.wtt.suburbanServices = self.parser.isolateSuburbanServices()

    def generate_visualization(self, skip_ac_reset=False):
        """generate RC -> reset flags -> apply filters -> build figure -> post-process"""
        qq = self.query

        # Merge current selections into pinned sets (accumulate)
        if qq.selectedLinks:
            pinned_set = set(qq.pinnedLinks)
            pinned_set.update(qq.selectedLinks)
            qq.pinnedLinks = list(pinned_set)
            qq.selectedLinks = []
        if qq.selectedServices:
            pinned_set = set(qq.pinnedServices)
            pinned_set.update(qq.selectedServices)
            qq.pinnedServices = list(pinned_set)
            qq.selectedServices = []

        # First-time backend build
        if not self.linkTimingsCreated:
            self.parser.wtt.generateRakeCycles(self.parser)
            self.parser.wtt.storeOriginalACStates()
            self.linkTimingsCreated = True
        elif not skip_ac_reset:
            self.parser.wtt.resetACStates()
            self.converted_links = []

        # Reset + filter
        self.filter_engine.reset_all_flags(self.parser.wtt)
        self.filter_engine.apply_filters(self.parser.wtt, qq)

        # Build figure
        fig = self.graph_builder.build_figure(self.parser.wtt, qq)

        # Station mode post-processing
        fig = self.graph_builder.post_process_station_mode(fig, qq, self.parser.wtt, self.parser)

        return fig

    def convert_to_ac(self, link_names):
        result = self.rake_ops.convert_to_ac(self.parser.wtt, link_names)
        self.converted_links.extend(result["links"])
        self._cached_report = None  # invalidate cache
        return result

    def _get_replacement_report(self):
        """Get cached ReplacementReport, recomputing if converted_links changed."""
        links_key = tuple(sorted(self.converted_links))
        if self._cached_report is not None and self._cached_report_links == links_key:
            return self._cached_report
        from gardi.core.replacement_analyzer import ReplacementAnalyzer
        analyzer = ReplacementAnalyzer(self.parser.wtt, self.parser)
        self._cached_report = analyzer.evaluate(self.converted_links)
        self._cached_report_links = links_key
        return self._cached_report

    def generate_replacement_report(self):
        from gardi.core.replacement_analyzer import format_report
        return format_report(self._get_replacement_report())

    def generate_replacement_xlsx(self):
        from gardi.core.replacement_analyzer import exportReportXlsx
        return exportReportXlsx(self._get_replacement_report())

    def build_service_table(self):
        return self.data_builder.build_service_table_data(
            self.parser.wtt, pinned_services=self.query.pinnedServices
        )

    def build_rake_table(self):
        return self.data_builder.build_rake_table_data(
            self.parser.wtt, pinned_links=self.query.pinnedLinks
        )

    def build_station_gap_summary(self):
        return self.data_builder.build_station_gap_summary(self.parser, self.query)

    def build_station_gap_detail(self, station_names):
        return self.data_builder.build_station_gap_detail(self.parser, station_names)

    def build_gap_distribution(self, detail_rows):
        return self.data_builder.build_gap_distribution(detail_rows)

    def build_all_station_distributions(self):
        return self.data_builder.build_all_station_distributions(self.parser)

    def reset_station_highlight(self, fig):
        self.graph_builder.reset_station_highlight(fig)

    def focus_event(self, fig, targets):
        self.graph_builder.focus_event(fig, targets)

    def export_xlsx(self):
        return self.data_builder.export_to_xlsx(self.parser.wtt)

    def export_results_text(self):
        return self.data_builder.export_results_text(self.parser.wtt, self.query)

    def generate_summary_status(self):
        return self.data_builder.generate_summary_status(self.parser.wtt, self.query)

    def highlight_links(self, fig, selected_links):
        self.graph_builder.highlight_links(fig, selected_links)

    def highlight_stations(self, fig, station_names):
        self.graph_builder.highlight_stations(fig, station_names)

    def highlight_services(self, fig, selected_services):
        self.graph_builder.highlight_services(fig, selected_services)

    def update_query_field(self, ctx, field, value_rakelink, value_service=None, value_station=None):
        if not ctx.triggered:
            return
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger.endswith("_service"):
            setattr(self.query, field, value_service)
        elif trigger.endswith("_station"):
            setattr(self.query, field, value_station)
        else:
            setattr(self.query, field, value_rakelink)

    def switch_filter_mode(self, active_tab, rk_time=None, svc_time=None, st_time=None):
        # save current
        if self.query.type:
            self.filterStates[self.query.type] = {
                "startStation": self.query.startStation,
                "endStation": self.query.endStation,
                "passingThrough": self.query.passingThrough.copy(),
                "inTimePeriod": self.query.inTimePeriod,
                "inDirection": self.query.inDirection,
            }

        # Update type
        if active_tab == "tab-rakelink":
            self.query.type = FilterType.RAKELINK
        elif active_tab == "tab-service":
            self.query.type = FilterType.SERVICE
        elif active_tab == "tab-station":
            self.query.type = FilterType.STATION

        # Restore saved state for new tab
        saved = self.filterStates.get(self.query.type, {})
        self.query.startStation = saved.get("startStation")
        self.query.endStation = saved.get("endStation")
        self.query.passingThrough = saved.get("passingThrough", [])
        self.query.inTimePeriod = saved.get("inTimePeriod", (165, 1605))
        self.query.inDirection = saved.get("inDirection")

    def build_query_info_panel(self):
        if self.query.type == FilterType.RAKELINK:
            return self._build_rake_link_query_info()
        elif self.query.type == FilterType.SERVICE:
            return self._build_service_query_info()
        else:
            return html.Div("No query context available.")

    def _build_service_query_info(self):
        if not self.query.selectedServices:
            return html.Div("No services selected.")

        selected_svcs = [
            svc
            for svc in self.parser.wtt.suburbanServices
            if any(str(sid) in self.query.selectedServices for sid in svc.serviceId)
        ]

        return html.Div(
            [
                html.Div(
                    "Selected Services",
                    style={
                        "fontSize": "13px",
                        "fontWeight": "600",
                        "color": "#475569",
                        "marginBottom": "6px",
                    },
                ),
                *[self._build_service_detail_block(svc) for svc in selected_svcs],
            ],
            style={"padding": "8px"},
        )

    def _build_service_detail_block(self, svc):
        svc_id_str = ",".join(str(sid) for sid in svc.serviceId)

        return html.Div(
            [
                html.Div(
                    f"Service {svc_id_str}",
                    style={"fontWeight": "600", "marginBottom": "4px"},
                ),
                html.Div(
                    f"{svc.direction.name} | {svc.initStation.name} -> {svc.finalStation.name}",
                    style={"fontSize": "12px", "color": "#64748b"},
                ),
                html.Div(
                    f"{'AC' if svc.needsACRake else 'Non-AC'} | {svc.rakeSizeReq}-car | {len(svc.events)} stops",
                    style={
                        "fontSize": "12px",
                        "color": "#64748b",
                        "marginBottom": "8px",
                    },
                ),
                html.Hr(style={"margin": "8px 0"}),
            ]
        )

    def _build_rake_link_query_info(self):
        if not self.query.selectedLinks:
            if self.converted_links:
                return self.buildACAnalysisPanel()
            return html.Div("No rake links selected.")

        selected_rcs = [
            rc
            for rc in self.parser.wtt.rakecycles
            if rc.linkName in self.query.selectedLinks
        ]

        rakelink_details = html.Div(
            [
                html.Div(
                    "Selected Rake Links",
                    style={
                        "fontSize": "13px",
                        "fontWeight": "600",
                        "color": "#475569",
                        "marginBottom": "6px",
                    },
                ),
                *[self._build_rake_path_block(rc) for rc in selected_rcs],
            ],
            style={"padding": "8px"},
        )

        # If AC conversions exist, show side-by-side layout + analysis below
        if self.converted_links:
            ac_panel = self.buildACAnalysisPanel()
            return html.Div([
                dbc.Row([
                    dbc.Col(rakelink_details, md=6),
                    dbc.Col(ac_panel, md=6),
                ], className="g-2"),
            ])

        return rakelink_details

    def _build_rake_path_block(self, rc):
        services = rc.servicePath
        n = len(services)

        start = services[0].initStation.name
        end = services[-1].finalStation.name

        ac = sum(1 for s in services if s.needsACRake)

        return html.Details(
            [
                html.Summary(
                    [
                        html.Span(f"Rake {rc.linkName}", style={"fontWeight": "600"}),
                        html.Span(
                            f"  * {len(services)} services *  ",
                            style={"color": "#64748b"},
                        ),
                        html.Span(f"{start} -> {end}"),
                        html.Span(
                            f"  {'AC' if ac == len(services) else 'Non-AC' if ac == 0 else 'Mixed AC'}",
                            style={"marginLeft": "6px", "color": "#475569"},
                        ),
                    ],
                    style={
                        "cursor": "pointer",
                        "fontSize": "13px",
                        "lineHeight": "1.4",
                    },
                ),
                html.Div(
                    [
                        build_service_row(svc, i < n - 1)
                        for i, svc in enumerate(services)
                    ],
                    style={"marginLeft": "14px", "marginTop": "6px"},
                ),
            ]
        )

    def buildACAnalysisPanel(self):
        """Build inline AC analysis visualizations from cached report."""
        import plotly.graph_objs as go
        from plotly.subplots import make_subplots

        report = self._get_replacement_report()
        children = []

        # 1. Before/After summary cards
        if report.beforeAfterMetrics:
            ba = report.beforeAfterMetrics
            b, a, d = ba["before"], ba["after"], ba["delta"]
            before_card = make_summary_card("Before Conversion", [
                f"AC services: {b['ac_services']}",
                f"AC coverage: {b['ac_pct']}%",
                f"Peak AC stops: {sum(b.get('peak_ac_frequency', {}).values())}",
            ])
            after_card = make_summary_card("After Conversion", [
                f"AC services: {a['ac_services']}",
                f"AC coverage: {a['ac_pct']}%",
                f"Peak AC stops: {sum(a.get('peak_ac_frequency', {}).values())}",
            ], footer=f"+{d['ac_services']} services (+{d['ac_pct']}%)")
            children.append(
                dbc.Row([
                    dbc.Col(before_card, width=6),
                    dbc.Col(after_card, width=6),
                ], className="g-2 mb-3")
            )

        # 2. AC density heatmap (before | after side-by-side)
        if report.acDensityByTod:
            density = report.acDensityByTod
            stations = density["stations"]
            buckets = density["buckets"]

            def make_z(data):
                return [[data[s].get(b, 0) for b in buckets] for s in stations]

            fig = make_subplots(rows=1, cols=2, subplot_titles=["Before", "After"],
                                horizontal_spacing=0.08)
            fig.add_trace(go.Heatmap(
                z=make_z(density["before"]), x=buckets, y=stations,
                colorscale="Blues", showscale=False,
            ), row=1, col=1)
            fig.add_trace(go.Heatmap(
                z=make_z(density["after"]), x=buckets, y=stations,
                colorscale="Blues", showscale=True,
                colorbar=dict(title="Services", len=0.8),
            ), row=1, col=2)
            fig.update_layout(
                height=max(200, len(stations) * 18 + 60),
                margin=dict(l=100, r=40, t=30, b=30),
                paper_bgcolor="white", plot_bgcolor="white",
                font=dict(size=11),
            )
            children.append(html.Div([
                html.Div("AC Service Density by Hour", style={
                    "fontSize": "13px", "fontWeight": "600", "color": "#475569", "marginBottom": "4px",
                }),
                dcc.Graph(id="ac-density-chart", figure=fig,
                          config={"displayModeBar": False},
                          style={"width": "100%"}),
            ], className="mb-3"))

        # 3. AC headway gaps bar chart
        if report.headwayGaps:
            gap_stations = [f"{e['station']} ({e['direction']})" for e in report.headwayGaps]
            default_station = gap_stations[0] if gap_stations else None

            # Build a dropdown + chart for the worst-gap station
            options = [{"label": s, "value": i} for i, s in enumerate(gap_stations)]

            # Default chart: worst station
            entry = report.headwayGaps[0]
            gap_fig = go.Figure(go.Bar(
                x=list(range(len(entry["gaps"]))),
                y=entry["gaps"],
                marker_color=["#ef4444" if g >= 15 else "#3b82f6" for g in entry["gaps"]],
            ))
            gap_fig.add_hline(y=15, line_dash="dash", line_color="#94a3b8",
                              annotation_text="15 min threshold")
            gap_fig.update_layout(
                height=200, margin=dict(l=40, r=20, t=10, b=30),
                paper_bgcolor="white", plot_bgcolor="white",
                xaxis_title="Gap #", yaxis_title="Minutes",
                font=dict(size=11),
            )

            children.append(html.Div([
                html.Div("AC Headway Gaps", style={
                    "fontSize": "13px", "fontWeight": "600", "color": "#475569", "marginBottom": "4px",
                }),
                dcc.Dropdown(
                    id="ac-headway-station-dropdown",
                    options=options,
                    value=0,
                    clearable=False,
                    style={"fontSize": "12px", "marginBottom": "4px"},
                ),
                dcc.Graph(id="ac-headway-chart", figure=gap_fig,
                          config={"displayModeBar": False},
                          style={"width": "100%"}),
            ], className="mb-3"))

        # 4. Followings adjacency heatmap
        fol = report.followings
        if fol and fol["nodes"] and fol["matrix"]:
            nodes = fol["nodes"]
            ac_pair_set = set(tuple(p) for p in fol.get("ac_ac_pairs", []))
            z = []
            annotations = []
            for i, row_node in enumerate(nodes):
                row_vals = []
                for j, col_node in enumerate(nodes):
                    if i == j:
                        row_vals.append(0)
                    else:
                        pair = tuple(sorted([row_node, col_node]))
                        w = fol["matrix"].get(pair, 0)
                        row_vals.append(w)
                        if pair in ac_pair_set and w > 0:
                            annotations.append(dict(
                                x=j, y=i, text="*", showarrow=False,
                                font=dict(color="red", size=10),
                            ))
                z.append(row_vals)

            fol_fig = go.Figure(go.Heatmap(
                z=z, x=nodes, y=nodes,
                colorscale="Viridis", showscale=True,
                colorbar=dict(title="Weight", len=0.8),
            ))
            fol_fig.update_layout(
                height=max(250, len(nodes) * 22 + 60),
                margin=dict(l=80, r=40, t=10, b=60),
                paper_bgcolor="white", plot_bgcolor="white",
                font=dict(size=10),
                annotations=annotations,
                xaxis=dict(tickangle=-45),
            )
            children.append(html.Div([
                html.Div("Link Followings (* = AC-AC pair)", style={
                    "fontSize": "13px", "fontWeight": "600", "color": "#475569", "marginBottom": "4px",
                }),
                dcc.Graph(id="ac-followings-chart", figure=fol_fig,
                          config={"displayModeBar": False},
                          style={"width": "100%"}),
            ], className="mb-3"))

        return html.Div(children, style={"padding": "8px"}) if children else html.Div()

    def _build_minimal_rake_block(self, rc):
        rows = []
        for i, svc in enumerate(rc.servicePath, start=1):
            rows.append(
                {
                    "seq": i,
                    "service_id": ", ".join(str(s) for s in svc.serviceId),
                    "start": svc.initStation.name,
                    "end": svc.finalStation.name,
                    "ac": "AC" if svc.needsACRake else "Non-AC",
                }
            )

        return html.Div(
            [
                html.Div(
                    f"Rake {rc.linkName} | "
                    f"{'AC' if rc.rake.isAC else 'Non-AC'} | "
                    f"{rc.rake.rakeSize} cars | "
                    f"{rc.lengthKm:.1f} km | "
                    f"{len(rc.servicePath)} services",
                    style={"fontWeight": "600", "marginBottom": "4px"},
                ),
                dash_table.DataTable(
                    columns=[
                        {"name": "#", "id": "seq"},
                        {"name": "Service ID", "id": "service_id"},
                        {"name": "From", "id": "start"},
                        {"name": "To", "id": "end"},
                        {"name": "AC?", "id": "ac"},
                    ],
                    data=rows,
                    page_size=8,
                    style_table={"maxHeight": "200px", "overflowY": "auto"},
                    style_cell={"fontSize": "12px", "padding": "4px"},
                ),
                html.Hr(),
            ]
        )

    def export_all_services_csv(self):
        return self.csv_builder.allServices(self.parser.wtt)

    def export_turnaround_csv(self):
        """Compute turnarounds for all terminal stations of rendered services."""
        terminals = set()
        for svc in self.parser.wtt.suburbanServices:
            if not svc.render or not svc.events:
                continue
            last_station = svc.events[-1].atStation
            if last_station:
                terminals.add(last_station)

        parts = []
        for station in sorted(terminals):
            try:
                csv_str = self.csv_builder.turnaround(self.parser.wtt, station)
                parts.append(csv_str)
            except ValueError:
                continue
        return "\n".join(parts) if parts else "# No turnaround data found\n"

    def export_timing_split_csv(self):
        return self.csv_builder.timingSplit(self.parser.wtt)

    def export_traversal_csv(self):
        return self.csv_builder.traversalTimes(self.parser.wtt)

    def export_pattern_csv(self):
        return self.csv_builder.patternSegments(self.parser.wtt)

    def is_valid_xlsx(self, filename):
        return bool(filename) and filename.lower().endswith(".xlsx")
