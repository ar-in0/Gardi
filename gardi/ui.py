
# ui.py
# This file defines the SimulatorUI class
# to modularize simulator.py

from dash import Dash, html, dcc, Input, Output, State, callback_context
from dash import dash_table
import dash_bootstrap_components as dbc

from gardi.core.data_builder import fmt_time, make_summary_card


def visualization_layout(graph_ready):
    """Create visualization graph component"""
    return dcc.Graph(
        id="rake-3d-graph",
        style={"height": "75vh", "display": "block" if graph_ready else "none"},
    )


def service_details_layout():
    """Placeholder for service details"""
    return html.Div("...", style={"padding": "20px"})


def build_service_row(svc, draw_connector):
    """Build a service row HTML component (moved from simulator.py)"""
    svc_id_str = ",".join(str(sid) for sid in svc.serviceId) if svc.serviceId else "?"

    row = html.Div(
        [
            html.Span(
                svc_id_str, style={"minWidth": "56px", "display": "inline-block"}
            ),
            html.Span(
                f"{svc.initStation.name} → {svc.finalStation.name} ({svc.direction})",
                style={"marginLeft": "6px"},
            ),
            html.Span(
                fmt_time(
                    next((e.atTime for e in svc.events if e.atTime is not None), None)
                ),
                style={"marginLeft": "6px", "color": "#64748b"},
            ),
        ],
        style={"fontSize": "12px"},
    )

    if not draw_connector:
        return row

    return html.Div([row, html.Div("│", style={"marginLeft": "6px"})])


# Factory methods for UI components
class UIComponents:
    @staticmethod
    def create_station_dropdown(
        component_id, placeholder="Select Station...", multi=False
    ):
        """Factory for station dropdowns"""
        return dcc.Dropdown(
            id=component_id,
            options=[],
            placeholder=placeholder,
            multi=multi,
            className="mb-3",
        )

    @staticmethod
    def create_time_slider(component_id, value=[165, 1605]):
        """Factory for time range sliders"""
        return dcc.RangeSlider(
            id=component_id,
            min=0,
            max=1440,
            step=15,
            value=value,
            marks={i: f"{(i // 60):02d}:{(i % 60):02d}" for i in range(0, 1441, 120)},
            tooltip={"placement": "bottom", "always_visible": False},
            allowCross=False,
        )

    @staticmethod
    def create_ac_selector(component_id="ac-selector", value="all"):
        """Factory for AC selector radio items"""
        return dbc.RadioItems(
            id=component_id,
            options=[
                {"label": "All", "value": "all"},
                {"label": "AC", "value": "ac"},
                {"label": "Non-AC", "value": "nonac"},
            ],
            value=value,
            inline=True,
            inputStyle={"marginRight": "6px"},
            labelStyle={"marginRight": "12px", "fontSize": "13px"},
        )


class GardiUI:
    def __init__(self):
        pass

    def drawTitle(self):
        return html.Div(
            [
                dcc.Markdown(
                    """
                        ## noGARDI
                        """.replace(
                        "  ", ""
                    ),
                    className="title",
                ),
                dcc.Markdown(
                    """
                        Timetable Visualization and Analysis
                        """.replace(
                        "  ", ""
                    ),
                    className="subtitle",
                ),
            ]
        )

    def drawUploadFullWTT(self):
        return dbc.Col(
            [
                dcc.Upload(
                    id="upload-wtt-inline",
                    children=html.Div(
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
                                "Full WTT",
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
                    style={
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
                    },
                    multiple=False,
                )
            ],
            xs=12,
            md=6,
            className="mb-3 mb-md-0",
        )

    def drawUploadWTTSummary(self):
        return dbc.Col(
            [
                dcc.Upload(
                    id="upload-summary-inline",
                    children=html.Div(
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
                                "Rake-Link Summary",
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
                    style={
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
                    },
                    multiple=False,
                )
            ],
            xs=12,
            md=6,
        )

    def drawUploadFiles(self):
        return html.Div(
            [
                #html.Div(
                #     [
                #         dcc.Markdown(
                #             "##### Upload Required Files", className="subtitle"
                #         ),
                #     ],
                #     style={"padding": "8px 0px"},
                # ),
                dbc.Row(
                    [
                        self.drawUploadFullWTT(),
                        self.drawUploadWTTSummary(),
                    ],
                    style={"padding": "0px 35px", "marginBottom": "20px"},
                ),
            ]
        )

    def drawACRadioButtons(self):
        return dbc.RadioItems(
            id="ac-selector",
            options=[
                {"label": "All", "value": "all"},
                {"label": "AC", "value": "ac"},
                {"label": "Non-AC", "value": "nonac"},
            ],
            value="all",
            inline=True,
            inputStyle={"marginRight": "6px"},
            labelStyle={
                "marginRight": "12px",
                "fontSize": "13px",
            },
            style={
                "marginTop": "8px",
                "marginBottom": "8px",
                "padding": "0px 35px",
            },
        )

    def drawRakeLinkFilters(self):
        return dbc.Tab(
            label="Rake Links",
            tab_id="tab-rakelink",
            children=dbc.Card(
                [
                    dbc.CardBody(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            html.Label(
                                                "Start Station",
                                                className="criteria-label",
                                            ),
                                            dcc.Dropdown(
                                                id="start-station",
                                                options=[],
                                                placeholder="Select Station...",
                                                className="mb-3",
                                                persistence=True,
                                                persistence_type="session",
                                            ),
                                        ],
                                        width=6,
                                    ),
                                    dbc.Col(
                                        [
                                            html.Label(
                                                "End Station",
                                                className="criteria-label",
                                            ),
                                            dcc.Dropdown(
                                                id="end-station",
                                                options=[],
                                                placeholder="Select Station...",
                                                className="mb-3",
                                            ),
                                        ],
                                        width=6,
                                    ),
                                ],
                                className="gx-2",
                            ),
                            html.Label(
                                "Passing Through",
                                className="criteria-label",
                            ),
                            dcc.Dropdown(
                                id="intermediate-stations",
                                options=[],
                                multi=True,
                                placeholder="Add intermediate stations",
                                className="mb-3",
                            ),
                            html.Label(
                                "In time period",
                                className="criteria-label",
                            ),
                            dcc.RangeSlider(
                                id="time-range-slider",
                                min=0,
                                max=1440,
                                step=15,
                                value=[165, 1605],
                                marks={
                                    i: f"{(i // 60):02d}:{(i % 60):02d}"
                                    for i in range(0, 1441, 120)
                                },
                                tooltip={
                                    "placement": "bottom",
                                    "always_visible": False,
                                },
                                allowCross=False,
                            ),
                        ]
                    )
                ],
                className="criteria-card mb-4",
                style={"margin": "0px 0px"},
            ),
        )

    def drawServiceFilters(self):
        return dbc.Tab(
            label="Services",
            tab_id="tab-service",
            children=dbc.Card(
                [
                    dbc.CardBody(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            html.Label(
                                                "Start Station",
                                                className="criteria-label",
                                            ),
                                            dcc.Dropdown(
                                                id="start-station_service",
                                                options=[],
                                                placeholder="Select Station...",
                                            ),
                                        ],
                                        width=6,
                                    ),
                                    dbc.Col(
                                        [
                                            html.Label(
                                                "End Station",
                                                className="criteria-label",
                                            ),
                                            dcc.Dropdown(
                                                id="end-station_service",
                                                options=[],
                                                placeholder="Select Station...",
                                            ),
                                        ],
                                        width=6,
                                    ),
                                ],
                                className="gx-2",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Passing Through",
                                        className="criteria-label me-2",
                                    ),
                                    html.Div(
                                        [
                                            dcc.Dropdown(
                                                id="intermediate-stations_service",
                                                options=[],
                                                multi=True,
                                                placeholder="Add intermediate stations",
                                                style={"flex": "1"},
                                            ),
                                            html.Div(
                                                [
                                                    dbc.Checklist(
                                                        options=[
                                                            {
                                                                "label": "UP",
                                                                "value": "UP",
                                                            },
                                                            {
                                                                "label": "DOWN",
                                                                "value": "DOWN",
                                                            },
                                                        ],
                                                        value=["UP", "DOWN"],
                                                        id="direction-selector",
                                                        inline=True,
                                                        switch=True,
                                                        className="ms-3 mb-0",
                                                    )
                                                ]
                                            ),
                                        ],
                                        className="d-flex align-items-center gap-2 mb-3",
                                        style={"width": "100%"},
                                    ),
                                ]
                            ),
                            html.Label(
                                "In time period",
                                className="criteria-label",
                            ),
                            dcc.RangeSlider(
                                id="time-range-slider_service",
                                min=0,
                                max=1440,
                                step=15,
                                value=[165, 1605],
                                marks={
                                    i: f"{(i // 60):02d}:{(i % 60):02d}"
                                    for i in range(0, 1441, 120)
                                },
                                tooltip={
                                    "placement": "bottom",
                                    "always_visible": False,
                                },
                                allowCross=False,
                            ),
                        ]
                    )
                ],
                className="criteria-card mb-4",
                style={"margin": "0px 0px"},
            ),
        )

    def drawStationFilters(self):
        return dbc.Tab(
            label="Stations",
            tab_id="tab-station",
            children=dbc.Card(
                [
                    dbc.CardBody(
                        [
                            html.Label(
                                "In time period",
                                className="criteria-label",
                            ),
                            dcc.RangeSlider(
                                id="time-range-slider_station",
                                min=0,
                                max=1440,
                                step=15,
                                value=[165, 1605],
                                marks={
                                    i: f"{(i // 60):02d}:{(i % 60):02d}"
                                    for i in range(0, 1441, 120)
                                },
                                tooltip={
                                    "placement": "bottom",
                                    "always_visible": False,
                                },
                                allowCross=False,
                            ),
                        ]
                    )
                ]
            ),
        )

    def drawTabbedFilters(self):
        return dbc.Tabs(
            id="filter-tabs",
            active_tab="tab-rakelink",
            children=[
                self.drawRakeLinkFilters(),
                self.drawServiceFilters(),
                self.drawStationFilters(),
            ],
            className="mb-4",
        )

    def drawFilters(self):
        return html.Div(
            [
                html.Div(
                    [
                        dcc.Markdown("##### View", className="subtitle"),
                    ],
                    style={"padding": "0px 0px"},
                ),
                self.drawACRadioButtons(),
                html.Div(id="filter-overlay", style={"display": "none"}),
                self.drawTabbedFilters(),
            ],
            style={"position": "relative"},
        )

    def drawGenerateButton(self):
        return html.Div(
            [
                html.Button(
                    "Generate",
                    id="generate-button",
                    n_clicks=0,
                    className="generate-button",
                    disabled=True,
                )
            ],
            style={"padding": "0px 35px"},
        )

    def drawLeftSidebar(self):
        return html.Div(
            [
                self.drawTitle(),
                html.Hr(),
                self.drawUploadFiles(),
                html.Hr(),
                self.drawFilters(),
                self.drawGenerateButton(),
            ],
            className="four columns sidebar",
        )

    def drawExportButtonRow(self):
        return html.Div(
            [
                dbc.ButtonGroup(
                    [
                        dbc.Button(
                            "Visualization",
                            id="mode-viz",
                            color="primary",
                            outline=True,
                            active=True,
                        ),
                        dbc.Button(
                            "Query Info",
                            id="mode-details",
                            color="primary",
                            outline=True,
                            active=False,
                        ),
                    ],
                    size="sm",
                    className="mode-pill-toggle",
                    style={"marginLeft": "20px"},
                ),
                html.Div(
                    dbc.Button(
                        "Convert to AC",
                        id="convert-ac-button",
                        color="primary",
                        outline=True,
                        disabled=True,
                    ),
                    style={"marginLeft": "auto", "marginRight": "8px"},
                ),
                html.Div(
                    dbc.Button(
                        "Reset",
                        id="reset-ac-button",
                        color="warning",
                        outline=True,
                        size="sm",
                    ),
                    style={"marginLeft": "4px", "display": "None"},
                ),
                html.Div(
                    dbc.Button(
                        "Export Summary",
                        id="export-button",
                        color="secondary",
                        outline=True,
                        disabled=True,
                    ),
                    className="ms-auto",
                ),
            ],
            className="d-flex align-items-center justify-content-between mb-2",
        )

    def drawGraphPlaneLinkTable(self):
        return [
            dcc.Graph(id="rake-3d-graph", style={"height": "65vh"}),
            html.Div(
                id="rake-link-table-container",
                children=[
                    html.Div(
                        id="rake-link-count",
                        style={
                            "marginBottom": "6px",
                            "fontWeight": "500",
                        },
                    ),
                    dash_table.DataTable(
                        id="rake-link-table",
                        columns=[
                            {"name": "Link", "id": "linkname"},
                            {"name": "Cars", "id": "cars"},
                            {"name": "AC?", "id": "is_ac"},
                            {
                                "name": "Length (km)",
                                "id": "length_km",
                            },
                            {"name": "Start", "id": "start"},
                            {"name": "End", "id": "end"},
                            {"name": "#Svcs", "id": "n_services"},
                        ],
                        data=[],
                        row_selectable="multi",
                        selected_rows=[],
                        page_size=45,
                        sort_action="native",
                        filter_action="native",
                        style_table={
                            "maxHeight": "260px",
                            "overflowY": "auto",
                        },
                        style_cell={
                            "padding": "6px",
                            "fontSize": "13px",
                        },
                    ),
                ],
                style={"padding": "10px 0px"},
            ),
        ]

    def drawServiceTable(self):
        return html.Div(
            id="service-table-container",
            children=[
                html.Hr(),
                html.Div(
                    id="service-count",
                    style={
                        "marginBottom": "6px",
                        "fontWeight": "500",
                    },
                ),
                dash_table.DataTable(
                    id="service-table",
                    columns=[
                        {
                            "name": "Service ID",
                            "id": "service_id",
                        },
                        {
                            "name": "Direction",
                            "id": "direction",
                        },
                        {"name": "AC?", "id": "is_ac"},
                        {"name": "Cars", "id": "cars"},
                        {
                            "name": "Start",
                            "id": "start_station",
                        },
                        {"name": "End", "id": "end_station"},
                        {
                            "name": "Start Time",
                            "id": "start_time",
                        },
                        {
                            "name": "Rake Link",
                            "id": "rake_link",
                        },
                    ],
                    data=[],
                    row_selectable="multi",
                    selected_rows=[],
                    page_size=45,
                    sort_action="native",
                    filter_action="native",
                    style_table={
                        "maxHeight": "260px",
                        "overflowY": "auto",
                    },
                    style_cell={
                        "padding": "6px",
                        "fontSize": "13px",
                    },
                ),
            ],
            style={
                "padding": "10px 0px",
                "display": "none",
            },
        )

    def drawDynamicContent(self):
        # We combine the graph/link table list with the service table component
        content_children = self.drawGraphPlaneLinkTable()
        content_children.append(self.drawServiceTable())

        return html.Div(
            id="viz-container",
            children=content_children,
            style={"position": "relative", "height": "75vh"},
        )

    def drawRightPanel(self):
        return html.Div(
            [
                dcc.Store(id="graph-ready", data=False),
                html.Div(id="status-div", className="text-box"),
                self.drawExportButtonRow(),
                dcc.Download(id="download-report"),
                self.drawDynamicContent(),
                html.Div(id="right-panel-content", style={"marginTop": "10px"}),
            ],
            className="eight columns",
            id="page",
        )

    def drawLayout(self):
        return html.Div(
            [
                dcc.Store(id="rl-table-store"),
                dcc.Store(id="app-state"),
                dcc.Store(id="backend-ready", data=False),
                self.drawLeftSidebar(),
                self.drawRightPanel(),
            ],
            className="row flex-display",
            style={"height": "100vh"},
        )
