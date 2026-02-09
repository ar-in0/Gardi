#!/usr/bin/env python3

from dash import html, dash_table

from gardi.core.parser import TimeTableParser
from gardi.core.filters import FilterType, FilterQuery, FilterEngine
from gardi.core.graph_builder import GraphBuilder
from gardi.core.data_builder import DataBuilder, fmt_time
from gardi.core.rake_operations import RakeOperations
from gardi.ui import build_service_row


class Gardi:
    def __init__(self):
        self.parser = None
        self.wttContents = None
        self.summaryContents = None
        self.wttFileName = None
        self.summaryFileName = None

        self.linkTimingsCreated = False

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

    def initialize_parser(self, wtt_file_obj):
        """Parse WTT, register stations, return station options."""
        if not self.parser:
            self.parser = TimeTableParser()

        self.parser.xlsxToDfFromFileObj(wtt_file_obj)
        self.parser.registerStations()

        stations = [s for s in self.parser.wtt.stations]
        options = [{"label": s, "value": s} for s in stations]
        return options

    def initialize_backend(self, summary_file_obj):
        """Parse summary, register services, isolate suburban."""
        self.parser.registerServices()
        self.parser.parseWttSummaryFromFileObj(summary_file_obj)
        self.parser.wtt.suburbanServices = self.parser.isolateSuburbanServices()

    def generate_visualization(self):
        """generate RC -> reset flags -> apply filters -> build figure -> post-process"""
        qq = self.query

        # First-time backend build
        if not self.linkTimingsCreated:
            self.parser.wtt.generateRakeCycles(self.parser)
            self.parser.wtt.storeOriginalACStates()
            self.linkTimingsCreated = True
        else:
            self.parser.wtt.resetACStates()

        # Reset + filter
        self.filter_engine.reset_all_flags(self.parser.wtt)
        self.filter_engine.apply_filters(self.parser.wtt, qq)

        # Build figure
        fig = self.graph_builder.build_figure(self.parser.wtt, qq)

        # Station mode post-processing
        fig = self.graph_builder.post_process_station_mode(fig, qq, self.parser.wtt, self.parser)

        # Re-apply highlighting if there were selections
        if qq.selectedLinks:
            self.graph_builder.highlight_links(fig, qq.selectedLinks)

        return fig

    def convert_to_ac(self, link_names):
        result = self.rake_ops.convert_to_ac(self.parser.wtt, link_names)
        return result

    def build_service_table(self):
        return self.data_builder.build_service_table_data(self.parser.wtt)

    def build_rake_table(self):
        return self.data_builder.build_rake_table_data(self.parser.wtt)

    def export_xlsx(self):
        return self.data_builder.export_to_xlsx(self.parser.wtt)

    def export_results_text(self):
        return self.data_builder.export_results_text(self.parser.wtt, self.query)

    def generate_summary_status(self):
        return self.data_builder.generate_summary_status(self.parser.wtt, self.query)

    def highlight_links(self, fig, selected_links):
        self.graph_builder.highlight_links(fig, selected_links)

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

    def update_query_type_time(self, active_tab, rk_time, svc_time, st_time):
        if active_tab == "tab-rakelink":
            self.query.type = FilterType.RAKELINK
            self.query.inTimePeriod = rk_time
            self.query.inDirection = None
        elif active_tab == "tab-service":
            self.query.type = FilterType.SERVICE
            self.query.inTimePeriod = svc_time
        elif active_tab == "tab-station":
            self.query.type = FilterType.STATION
            self.query.inTimePeriod = st_time

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
                    f"{svc.direction.name} | {svc.initStation.name} → {svc.finalStation.name}",
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
            return html.Div("No rake links selected.")

        selected_rcs = [
            rc
            for rc in self.parser.wtt.rakecycles
            if rc.linkName in self.query.selectedLinks
        ]

        return html.Div(
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
                            f"  · {len(services)} services ·  ",
                            style={"color": "#64748b"},
                        ),
                        html.Span(f"{start} → {end}"),
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

    def is_valid_xlsx(self, filename):
        return bool(filename) and filename.lower().endswith(".xlsx")
