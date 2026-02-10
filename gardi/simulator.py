#!/usr/bin/env python3

import os
import dash
import io
import base64
import plotly.graph_objs as go

from dash import dcc, html, Input, Output, State, callback_context
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from datetime import datetime

from gardi.gardi import Gardi
from gardi.core.filters import FilterType
from gardi.ui import GardiUI


class Simulator:
    def __init__(self, debug=False):
        assets_dir = os.path.join(os.path.dirname(__file__), "assets")
        self.app = dash.Dash(
            external_stylesheets=[dbc.themes.BOOTSTRAP],
            assets_folder=assets_dir,
        )
        self.gardi = Gardi()
        self._ui = GardiUI()

        self.app.layout = self._ui.drawLayout()
        self._init_callbacks()

        self.debug = debug

    def _init_callbacks(self):
        self._init_file_upload_callbacks()
        self._init_filter_query_callbacks()
        self._init_button_callbacks()

    def _make_upload_callback(self, component_id, label, contents_attr, filename_attr):
        @self.app.callback(
            Output(component_id, "children"),
            Output(component_id, "style"),
            Input(component_id, "contents"),
            State(component_id, "filename"),
        )
        def update_filename(contents, filename):
            base_style = {
                "height": "140px",
                "borderWidth": "2px",
                "borderStyle": "dashed",
                "borderRadius": "12px",
                "borderColor": "#cbd5e1",
                "display": "flex",
                "alignItems": "center",
                "justifyContent": "center",
                "cursor": "pointer",
                "transition": "all 0.2s ease",
            }
            if contents is None:
                return (
                    html.Div(
                        [
                            html.Img(
                                src="/assets/excel-icon.png",
                                style={
                                    "width": "28px",
                                    "height": "28px",
                                    "marginBottom": "6px",
                                },
                            ),
                            html.Div(
                                label,
                                style={
                                    "fontWeight": "500",
                                    "color": "#334155",
                                    "fontSize": "14px",
                                },
                            ),
                            html.Div(
                                "Click to upload",
                                style={
                                    "fontSize": "11px",
                                    "color": "#94a3b8",
                                    "marginTop": "4px",
                                },
                            ),
                        ],
                        className="text-center",
                    ),
                    base_style,
                )

            setattr(self.gardi, contents_attr, contents)
            setattr(self.gardi, filename_attr, filename)
            display_name = filename if len(filename) <= 40 else filename[:37] + "..."

            success_style = {**base_style, "borderStyle": "solid", "borderColor": "#188038"}

            return (
                html.Div(
                    [
                        html.Img(
                            src="/assets/excel-icon.png",
                            style={
                                "width": "24px",
                                "height": "24px",
                                "marginBottom": "4px",
                            },
                        ),
                        html.Div(
                            display_name,
                            style={
                                "fontSize": "11px",
                                "color": "#188038",
                                "fontWeight": "500",
                                "wordBreak": "break-all",
                            },
                        ),
                    ],
                    className="text-center",
                ),
                success_style,
            )

    def _init_file_upload_callbacks(self):
        self._make_upload_callback("upload-wtt-inline", "Full WTT", "wttContents", "wttFileName")
        self._make_upload_callback("upload-summary-inline", "WTT Link Summary", "summaryContents", "summaryFileName")

        @self.app.callback(
            Output("generate-button", "disabled"),
            Output("generate-button", "style"),
            [
                Input("upload-wtt-inline", "contents"),
                Input("upload-summary-inline", "contents"),
                Input("backend-ready", "data"),
            ],
        )
        def enable_generate_button(wtt_contents, summary_contents, backend_ready):
            base_style = {
                "border": "none",
                "width": "100%",
                "height": "42px",
                "borderRadius": "8px",
                "fontWeight": "600",
                "fontSize": "14px",
                "cursor": "pointer",
                "transition": "all 0.2s ease",
            }

            if wtt_contents is not None and summary_contents is not None and backend_ready:
                enabled_style = base_style | {"opacity": "1"}
                return False, enabled_style
            else:
                disabled_style = base_style | {
                    "color": "#94a3b8",
                    "cursor": "not-allowed",
                    "opacity": "0.65",
                }
                return True, disabled_style

        @self.app.callback(
            [
                Output("start-station", "disabled"),
                Output("end-station", "disabled"),
                Output("intermediate-stations", "disabled"),
                Output("time-range-slider", "disabled"),
                Output("filter-overlay", "style"),
            ],
            [
                Input("upload-wtt-inline", "contents"),
                Input("upload-summary-inline", "contents"),
            ],
        )
        def toggle_filters(wtt_contents, summary_contents):
            if wtt_contents is not None and summary_contents is not None:
                overlay_style = {"display": "none"}
                return False, False, False, False, overlay_style
            else:
                overlay_style = {
                    "position": "absolute",
                    "top": "0",
                    "left": "0",
                    "right": "0",
                    "bottom": "0",
                    "backgroundColor": "rgba(243, 246, 250, 0.7)",
                    "zIndex": "10",
                    "cursor": "not-allowed",
                    "borderRadius": "12px",
                }
                return True, True, True, True, overlay_style

        @self.app.callback(
            [
                Output("app-state", "data"),
                Output("start-station", "options"),
                Output("end-station", "options"),
                Output("intermediate-stations", "options"),
                Output("start-station_service", "options"),
                Output("end-station_service", "options"),
                Output("intermediate-stations_service", "options"),
            ],
            Input("upload-wtt-inline", "contents"),
        )
        def init_filters(wttContents):
            if not self.gardi.is_valid_xlsx(self.gardi.wttFileName):
                raise PreventUpdate
            if not wttContents:
                return None, [], [], [], [], [], []

            wttDecoded = base64.b64decode(wttContents.split(",")[1])
            wttIO = io.BytesIO(wttDecoded)

            options = self.gardi.initialize_parser(wttIO)

            return (
                {"initialized": True},
                options, options, options,
                options, options, options,
            )

        @self.app.callback(
            Output("backend-ready", "data"),
            [
                Input("app-state", "data"),
                Input("upload-summary-inline", "contents"),
            ],
            prevent_initial_call=True,
        )
        def init_backend(app_state, summaryContents):
            if not app_state or not app_state.get("initialized"):
                raise PreventUpdate
            if summaryContents is None:
                return False

            if not self.gardi.is_valid_xlsx(self.gardi.summaryFileName):
                raise PreventUpdate

            try:
                summaryDecoded = base64.b64decode(summaryContents.split(",")[1])
                summaryIO = io.BytesIO(summaryDecoded)
                self.gardi.initialize_backend(summaryIO)
                return True
            except Exception as e:
                print(f"Error initializing backend: {e}")
                return False

    def _init_filter_query_callbacks(self):

        @self.app.callback(
            Input("start-station", "value"),
            Input("start-station_service", "value"),
        )
        def update_start_station(value_rakelink, value_service):
            self.gardi.update_query_field(
                callback_context, "startStation", value_rakelink, value_service
            )
            return None

        @self.app.callback(
            Input("end-station", "value"),
            Input("end-station_service", "value"),
        )
        def update_end_station(value_rakelink, value_service):
            self.gardi.update_query_field(
                callback_context, "endStation", value_rakelink, value_service
            )
            return None

        @self.app.callback(
            Input("intermediate-stations", "value"),
            Input("intermediate-stations_service", "value"),
        )
        def update_passing_through(value_rakelink, value_service):
            v1 = value_rakelink or []
            v2 = value_service or []
            self.gardi.update_query_field(
                callback_context, "passingThrough", v1, v2
            )
            return None

        @self.app.callback(
            Input("time-range-slider", "value"),
            Input("time-range-slider_service", "value"),
            Input("time-range-slider_station", "value"),
            prevent_initial_call=False,
        )
        def update_time_period(value_rakelink, value_service, value_station):
            self.gardi.update_query_field(
                callback_context,
                "inTimePeriod",
                value_rakelink,
                value_service,
                value_station,
            )
            return None

        @self.app.callback(
            Input("ac-selector", "value"),
        )
        def update_ac_filter(value_rakelink):
            self.gardi.update_query_field(
                callback_context, "ac", value_rakelink
            )
            return None

        @self.app.callback(
            Input("direction-selector", "value"),
        )
        def update_service_direction(value):
            self.gardi.query.inDirection = value
            return None

        @self.app.callback(
            Output("app-state", "data", allow_duplicate=True),
            Input("filter-tabs", "active_tab"),
            prevent_initial_call=True,
        )
        def switch_filter_tab(active_tab):
            self.gardi.switch_filter_mode(active_tab)
            return None

    def _init_button_callbacks(self):

        @self.app.callback(
            Output("rake-3d-graph", "figure", allow_duplicate=True),
            Output("rake-link-table", "data", allow_duplicate=True),
            Output("status-div", "children", allow_duplicate=True),
            Input("reset-ac-button", "n_clicks"),
            State("rake-3d-graph", "figure"),
            prevent_initial_call=True,
        )
        def reset_ac_conversions(n_clicks, current_fig):
            if not n_clicks:
                raise PreventUpdate
            status_msg = html.Div(
                "Reset functionality requires storing original state",
                style={"padding": "8px", "color": "#f59e0b"},
            )
            raise PreventUpdate

        @self.app.callback(
            Output("convert-ac-button", "disabled"),
            Input("rake-link-table", "selected_rows"),
            Input("filter-tabs", "active_tab"),
            State("rake-link-table", "data"),
            prevent_initial_call=True,
        )
        def toggle_convert_button(selected_rows, active_tab, table_data):
            if active_tab != "tab-rakelink" or not selected_rows or not table_data:
                return True

            has_nonac = False
            for idx in selected_rows:
                if idx < len(table_data):
                    if table_data[idx]["is_ac"] == "Non-AC":
                        has_nonac = True
                        break

            return not has_nonac

        @self.app.callback(
            Output("rake-3d-graph", "figure", allow_duplicate=True),
            Output("rake-link-table", "data", allow_duplicate=True),
            Output("status-div", "children", allow_duplicate=True),
            Input("convert-ac-button", "n_clicks"),
            State("rake-link-table", "selected_rows"),
            State("rake-link-table", "data"),
            State("rake-3d-graph", "figure"),
            prevent_initial_call=True,
        )
        def handle_ac_conversion(n_clicks, selected_rows, table_data, current_fig):
            if not n_clicks or not selected_rows or not table_data:
                raise PreventUpdate

            selected_links = [
                table_data[idx]["linkname"]
                for idx in selected_rows
                if idx < len(table_data)
            ]

            result = self.gardi.convert_to_ac(selected_links)

            updated_table = table_data.copy()
            for row in updated_table:
                if row["linkname"] in result["links"]:
                    row["is_ac"] = "AC"

            # Regenerate visualization (keep the AC conversion we just applied)
            fig = self.gardi.generate_visualization(skip_ac_reset=True)

            status_msg = html.Div(
                [
                    html.Span(f"Converted {result['converted']} rake link(s) to AC: "),
                    html.Span(", ".join(result["links"]), style={"fontWeight": "500"}),
                ],
                style={
                    "padding": "8px 12px",
                    "borderLeft": "3px solid #10b981",
                    "borderRadius": "4px",
                    "marginBottom": "8px",
                },
            )

            return fig, updated_table, status_msg

        @self.app.callback(
            Output("rake-link-table-container", "style"),
            Output("service-table-container", "style"),
            Input("filter-tabs", "active_tab"),
            Input("graph-ready", "data"),
        )
        def toggle_table_display(active_tab, graph_ready):
            if not graph_ready:
                return {"display": "none"}, {"display": "none"}

            if active_tab == "tab-service":
                return {"display": "none"}, {"padding": "10px 0px", "display": "block"}
            else:
                return {"padding": "10px 0px", "display": "block"}, {"display": "none"}

        @self.app.callback(
            Output("rake-3d-graph", "figure", allow_duplicate=True),
            Input("service-table", "selected_rows"),
            State("rake-3d-graph", "figure"),
            State("service-table", "data"),
            State("filter-tabs", "active_tab"),
            prevent_initial_call=True,
        )
        def update_graph_from_service_selection(
            selected_rows, current_fig, table_data, active_tab
        ):
            if (
                active_tab != "tab-service"
                or current_fig is None
                or not current_fig.get("data")
            ):
                raise PreventUpdate

            if not selected_rows or not table_data:
                selected_services = []
            else:
                selected_services = [
                    table_data[idx]["service_id"]
                    for idx in selected_rows
                    if idx < len(table_data)
                ]

            self.gardi.query.selectedServices = selected_services

            fig = go.Figure(current_fig)
            self.gardi.highlight_services(fig, selected_services)

            return fig

        @self.app.callback(
            Output("service-table", "selected_rows"),
            Input("rake-3d-graph", "clickData"),
            State("service-table", "data"),
            State("service-table", "selected_rows"),
            State("filter-tabs", "active_tab"),
            prevent_initial_call=True,
        )
        def toggle_service_from_graph(
            clickData, table_rows, current_selection, active_tab
        ):
            if active_tab != "tab-service" or not clickData or not table_rows:
                return current_selection or []

            try:
                hover_text = clickData["points"][0].get("hovertext", "")
                parts = hover_text.split(":")[0].strip()
                if "-" in parts:
                    clicked_service = parts.split("-")[1]
                else:
                    return current_selection or []
            except (KeyError, IndexError) as e:
                print(f"Error extracting clicked service: {e}")
                return current_selection or []

            clicked_idx = None
            for idx, row in enumerate(table_rows):
                if clicked_service in row.get("service_id", ""):
                    clicked_idx = idx
                    break

            if clicked_idx is None:
                return current_selection or []

            selected = list(current_selection or [])
            if clicked_idx in selected:
                selected.remove(clicked_idx)
            else:
                selected.append(clicked_idx)

            return selected

        @self.app.callback(
            Output("rake-3d-graph", "figure", allow_duplicate=True),
            Input("rake-link-table", "selected_rows"),
            State("rake-3d-graph", "figure"),
            State("rake-link-table", "data"),
            prevent_initial_call=True,
        )
        def update_graph_highlighting(selected_rows, current_fig, table_data):
            if current_fig is None or not current_fig.get("data"):
                raise PreventUpdate

            if not selected_rows or not table_data:
                selected_links = []
            else:
                selected_links = [
                    table_data[idx]["linkname"]
                    for idx in selected_rows
                    if idx < len(table_data)
                ]

            self.gardi.query.selectedLinks = selected_links

            fig = go.Figure(current_fig)
            self.gardi.highlight_links(fig, selected_links)

            return fig

        @self.app.callback(
            Output("service-table", "data"),
            Output("service-count", "children"),
            Input("graph-ready", "data"),
            Input("ac-selector", "value"),
            State("filter-tabs", "active_tab"),
            prevent_initial_call=True,
        )
        def build_service_table(graph_ready, ac_select, active_tab):
            is_service_mode = (
                active_tab == "tab-service"
                or self.gardi.query.type == FilterType.SERVICE
            )

            if not graph_ready or self.gardi.parser is None or not is_service_mode:
                return [], ""

            rows = self.gardi.build_service_table()
            return rows, f"{len(rows)} services"

        @self.app.callback(
            Output("rake-link-table", "data"),
            Output("rl-table-store", "data"),
            Output("rake-link-count", "children"),
            Input("graph-ready", "data"),
            Input("ac-selector", "value"),
            State("upload-wtt-inline", "contents"),
            State("upload-summary-inline", "contents"),
            prevent_initial_call=True,
        )
        def build_rake_table(graph_ready, ac_select, wttContents, summaryContents):
            if not graph_ready or self.gardi.parser is None:
                return [], [], ""

            rows = self.gardi.build_rake_table()
            return rows, rows, f"{len(rows)} rake links"

        @self.app.callback(
            Output("right-panel-content", "children", allow_duplicate=True),
            Input("rake-link-table", "selected_rows"),
            State("mode-details", "active"),
            prevent_initial_call=True,
        )
        def update_query_info_on_selection(selected_rows, details_active):
            if not details_active:
                raise PreventUpdate
            return self.gardi.build_query_info_panel()

        @self.app.callback(
            Output("rake-link-table", "selected_rows"),
            Input("rake-3d-graph", "clickData"),
            State("rake-link-table", "data"),
            State("rake-link-table", "selected_rows"),
            prevent_initial_call=True,
        )
        def toggle_row_from_graph(clickData, table_rows, current_selection):
            if not clickData or not table_rows:
                return current_selection or []

            try:
                hover_text = clickData["points"][0].get("hovertext", "")
                clicked_link = hover_text.split(":")[0].strip()
                clicked_link = clicked_link.split("-")[0]
                print(f"Clicked link from graph: {clicked_link}")
            except (KeyError, IndexError) as e:
                print(f"Error extracting clicked link: {e}")
                return current_selection or []

            clicked_idx = None
            for idx, row in enumerate(table_rows):
                if row.get("linkname") == clicked_link:
                    clicked_idx = idx
                    break

            if clicked_idx is None:
                print(f"Link {clicked_link} not found in table")
                return current_selection or []

            selected = list(current_selection or [])
            if clicked_idx in selected:
                selected.remove(clicked_idx)
                print(f"Removed {clicked_link} from selection")
            else:
                selected.append(clicked_idx)
                print(f"Added {clicked_link} to selection")

            return selected

        @self.app.callback(
            Output("app-state", "data", allow_duplicate=True),
            Input("rake-link-table", "selected_rows"),
            State("rake-link-table", "data"),
            prevent_initial_call=True,
        )
        def update_selected_rakes(selected_rows, table_data):
            if not selected_rows or not table_data:
                self.gardi.query.selectedLinks = []
                return {"selectedLinks": []}

            selected_links = [
                table_data[idx]["linkname"]
                for idx in selected_rows
                if idx < len(table_data)
            ]

            self.gardi.query.selectedLinks = selected_links
            return {"selectedLinks": selected_links}

        @self.app.callback(
            Output("viz-container", "style"),
            Output("right-panel-content", "children"),
            Output("mode-viz", "active"),
            Output("mode-details", "active"),
            Input("mode-viz", "n_clicks"),
            Input("mode-details", "n_clicks"),
        )
        def switch_right_panel(viz_clicks, details_clicks):
            ctx = dash.callback_context.triggered_id

            if ctx == "mode-details":
                return (
                    {"display": "none"},
                    self.gardi.build_query_info_panel(),
                    False,
                    True,
                )

            return {"display": "block"}, html.Div(), True, False

        @self.app.callback(
            Output("status-div", "children"),
            Output("rake-3d-graph", "figure"),
            Output("export-button", "disabled"),
            Output("graph-ready", "data"),
            Output("rake-link-table", "selected_rows", allow_duplicate=True),
            Output("service-table", "selected_rows", allow_duplicate=True),
            Input("generate-button", "n_clicks"),
            Input("rake-3d-graph", "clickData"),
            Input("ac-selector", "value"),
            State("upload-wtt-inline", "contents"),
            State("upload-summary-inline", "contents"),
            prevent_initial_call=True,
        )
        def on_generate_click(
            n_clicks, clickData, ac_status, wttContents, summaryContents
        ):
            if n_clicks == 0 or wttContents is None or summaryContents is None:
                return "", go.Figure(), True, False, [], []

            try:
                self.gardi.query.ac = ac_status
                self.gardi.query.selectedLinks = []
                self.gardi.query.selectedServices = []

                fig = self.gardi.generate_visualization()

                return html.Div(), fig, False, True, [], []

            except Exception as e:
                import traceback
                traceback.print_exc()
                return (html.Div(f"Error: {e}"), go.Figure(), True, False, [], [])

        @self.app.callback(
            Output("download-report", "data"),
            Input("export-button", "n_clicks"),
            prevent_initial_call=True,
        )
        def trigger_download(n_clicks):
            filter_type = self.gardi.query.type.value if self.gardi.query.type else "unknown"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename_xlsx = f"WTT_Export_{filter_type}_{timestamp}.xlsx"

            report_xlsx = self.gardi.export_xlsx()
            return dcc.send_data_frame(report_xlsx.to_excel, filename_xlsx, index=False)

    def run(self, host, port):
        self.app.run(debug=self.debug, host=host, port=port)
