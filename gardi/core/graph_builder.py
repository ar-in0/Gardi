#!/usr/bin/env python3

import plotly.graph_objs as go
from gardi.core.filters import FilterType
from gardi.core.models import DISTANCE_MAP


OFF_NETWORK_Y = {
    "CHATTRAPATI SHIVAJI MAHARAJ TERMINUS": -2,
    "PANVEL": -6,
}


class GraphBuilder:
    def build_figure(self, wtt, query, distance_map=None):
        if distance_map is None:
            distance_map = DISTANCE_MAP

        pinned_links = set(query.pinnedLinks) if query.pinnedLinks else set()
        pinned_services = set(query.pinnedServices) if query.pinnedServices else set()

        rakecycles = [rc for rc in wtt.rakecycles if rc.servicePath]
        print(f"We have  len {len(rakecycles)}")
        if not rakecycles:
            raise ValueError("No valid rakecycles found.")

        stationToY = {st.upper(): distance_map[st.upper()] for st in distance_map}

        all_traces = []
        z_labels = []
        z_offset = 0

        # filter mmode
        is_service_filter = query.type == FilterType.SERVICE

        if is_service_filter:
            # 2 traces: AC and non-AC
            batches = {
                True:  {"x": [], "y": [], "z": [], "hover": [], "custom": []},
                False: {"x": [], "y": [], "z": [], "hover": [], "custom": []},
            }

            for rc in rakecycles:
                for svc in rc.servicePath:
                    svc_id_str = (
                        ",".join(str(sid) for sid in svc.serviceId)
                        if svc.serviceId
                        else "?"
                    )
                    if not svc.render and svc_id_str not in pinned_services:
                        z_offset += 40
                        continue

                    batch = batches[svc.needsACRake]
                    has_points = False

                    for ev in svc.events:
                        if ev.isTerminalDeparture:
                            continue
                        stName = str(ev.atStation).strip().upper()
                        if stName not in stationToY:
                            continue
                        batch["x"].append(ev.atTime)
                        batch["y"].append(stationToY[stName])
                        batch["z"].append(z_offset)
                        batch["hover"].append(
                            f"{rc.linkName}-{svc_id_str}: {stName} @ {(int(ev.atTime)//60) % 24:02d}:{int(ev.atTime%60):02d}"
                        )
                        batch["custom"].append(svc_id_str)
                        has_points = True

                    # break line between services
                    if has_points:
                        batch["x"].append(None)
                        batch["y"].append(None)
                        batch["z"].append(None)
                        batch["hover"].append(None)
                        batch["custom"].append(None)

                    z_labels.append((z_offset, f"{rc.linkName}-{svc_id_str}"))
                    z_offset += 40

            for is_ac, b in batches.items():
                if not any(v is not None for v in b["x"]):
                    continue
                color = "rgba(66,133,244,0.8)" if is_ac else "rgba(90,90,90,0.8)"
                all_traces.append(go.Scatter3d(
                    x=b["x"], y=b["y"], z=b["z"],
                    mode="lines+markers",
                    line=dict(color=color),
                    marker=dict(size=2, color=color),
                    hovertext=b["hover"],
                    hoverinfo="text",
                    customdata=b["custom"],
                    name="AC Services" if is_ac else "Non-AC Services",
                    meta={"ac": is_ac},
                    visible=True,
                ))

        else:
            for rc in rakecycles:
                if not rc.render and rc.linkName not in pinned_links:
                    continue

                mode = "lines+markers"

                # enumerate rakelink events
                x, y, z, stationLabels, svcIds = [], [], [], [], []
                off_network_buffer = []
                last_on_network = None
                gaps = []

                for svc in rc.servicePath:
                    if not svc.render:
                        continue
                    svc_id_str = (
                        ",".join(str(sid) for sid in svc.serviceId)
                        if svc.serviceId
                        else "?"
                    )
                    for ev in svc.events:
                        if not ev.atTime or not ev.atStation:
                            continue

                        if not ev.render:
                            continue

                        minutes = ev.atTime

                        stName = str(ev.atStation).strip().upper()
                        if stName not in stationToY:
                            off_network_buffer.append((stName, minutes))
                            continue

                        if off_network_buffer and last_on_network:
                            # Break the line before this point
                            for lst in (x, y, z, stationLabels, svcIds):
                                lst.append(None)
                            end_point = (minutes, stationToY[stName], z_offset)
                            gaps.append((last_on_network, end_point, off_network_buffer, svc_id_str))
                            off_network_buffer = []

                        x.append(minutes)
                        y.append(stationToY[stName])
                        z.append(z_offset)
                        stationLabels.append(stName)
                        svcIds.append(svc_id_str)
                        last_on_network = (x[-1], y[-1], z[-1])

                # rakelink trace
                if x:
                    color = (
                        "rgba(66,133,244,0.8)" if rc.rake.isAC else "rgba(90,90,90,0.8)"
                    )

                    all_traces.append(
                        go.Scatter3d(
                            x=x,
                            y=y,
                            z=z,
                            mode=mode,
                            line=dict(color=color),
                            marker=dict(size=2, color=color),
                            hovertext=[
                                f"{rc.linkName}-{sid}: {st} @ {(int(xx)//60) % 24:02d}:{int(xx%60):02d}"
                                if xx is not None else None
                                for xx, st, sid in zip(x, stationLabels, svcIds)
                            ],
                            hoverinfo="text",
                            name=rc.linkName,
                            meta={"ac": rc.rake.isAC},
                            visible=True,
                        )
                    )
                    # Add orange dashed connectors for off-network gaps
                    for start, end, via_stops, sid in gaps:
                        gap_x = [start[0]]
                        gap_y = [start[1]]
                        gap_z = [start[2]]
                        gap_hover = []
                        via_names = []
                        gap_hover.append(f"{rc.linkName}-{sid}: leaving WR network")
                        for off_name, off_time in via_stops:
                            via_names.append(off_name)
                            off_y = OFF_NETWORK_Y.get(off_name, -5)
                            gap_x.append(off_time)
                            gap_y.append(off_y)
                            gap_z.append(start[2])
                            gap_hover.append(
                                f"{rc.linkName}-{sid}: {off_name} @ "
                                f"{(int(off_time)//60) % 24:02d}:{int(off_time)%60:02d}"
                            )
                        gap_x.append(end[0])
                        gap_y.append(end[1])
                        gap_z.append(end[2])
                        via_label = ", ".join(sorted(set(via_names)))
                        gap_hover.append(f"{rc.linkName}-{sid}: back on WR via {via_label}")
                        all_traces.append(go.Scatter3d(
                            x=gap_x,
                            y=gap_y,
                            z=gap_z,
                            mode="lines+markers",
                            line=dict(color="rgba(255,165,0,0.9)", dash="dash", width=4),
                            marker=dict(size=4, color="rgba(255,165,0,0.9)", symbol="diamond"),
                            hovertext=gap_hover,
                            hoverinfo="text",
                            name=rc.linkName,
                            showlegend=False,
                        ))

                    z_labels.append((z_offset, rc.linkName))
                    z_offset += 40

        if query.inTimePeriod and query.type == FilterType.SERVICE:
            x_start, x_end = query.inTimePeriod
            x_end += 90  # padding
        else:
            x_start, x_end = 165, 1605

        tickPositions = list(range(x_start, x_end + 1, 120))
        tickLabels = [f"{(t // 60) % 24:02d}:{int(t % 60):02d}" for t in tickPositions]

        yTickVals = list(stationToY.values())
        yTickText = list(stationToY.keys())
        # Add off-network stations to Y axis
        for name, yval in OFF_NETWORK_Y.items():
            yTickVals.append(yval)
            yTickText.append(name)

        fig = go.Figure(data=all_traces)

        fig.update_layout(
            font=dict(size=12, color="#CCCCCC"),
            scene=dict(
                xaxis=dict(
                    showgrid=True,
                    showspikes=False,
                    title="Time of Day ->",
                    range=[x_start, x_end],
                    tickvals=tickPositions,
                    ticktext=tickLabels,
                ),
                yaxis=dict(
                    showgrid=True,
                    showspikes=False,
                    title="",
                    tickvals=yTickVals,
                    ticktext=yTickText,
                    range=[min(yTickVals), max(yTickVals)],
                    autorange=False,
                ),
                zaxis=dict(
                    showgrid=True,
                    showspikes=False,
                    title="Service" if is_service_filter else "Rake Cycle",
                    tickvals=[zv for zv, _ in z_labels],
                    ticktext=[zl for _, zl in z_labels],
                ),
                camera=dict(
                    eye=dict(x=0, y=0, z=2.5),
                    up=dict(x=0, y=1, z=0),
                    center=dict(x=0, y=0, z=0),
                ),
                aspectmode="manual",
                aspectratio=dict(x=2.8, y=1.2, z=1.2),
            ),
            scene_camera_projection_type="orthographic",
            updatemenus=[],
            width=1300,
            height=700,
            margin=dict(t=30, l=5, b=5, r=5),
            autosize=True,
            meta={
                "x_range": [x_start, x_end],
                "x_tickvals": tickPositions,
                "x_ticktext": tickLabels,
                "y_range": [min(yTickVals), max(yTickVals)],
            },
        )

        return fig

    def highlight_services(self, fig, selected_services):
        selected_set = set(selected_services)

        # Remove any prior overlay traces
        fig.data = [t for t in fig.data if t.name != "__selected"]

        for trace in fig.data:
            if trace.name == "__focus":
                continue
            cd = trace.customdata
            if cd is not None and len(cd) > 0:
                is_ac = isinstance(trace.meta, dict) and trace.meta.get("ac", False)
                r, g, b = (66, 133, 244) if is_ac else (90, 90, 90)

                if not selected_set:
                    # Reset to original appearance
                    base_color = f"rgba({r},{g},{b},0.8)"
                    trace.marker.color = base_color
                    trace.marker.size = 2
                    trace.marker.opacity = 1
                    trace.line.color = base_color
                    trace.hoverinfo = "text"
                else:
                    # Dim the entire original trace
                    dim_color = f"rgba({r},{g},{b},0.05)"
                    trace.marker.color = dim_color
                    trace.marker.size = 1
                    trace.marker.opacity = 1
                    trace.line.color = dim_color
                    trace.hoverinfo = "skip"

                    # Build overlay traces for selected services
                    bright_color = f"rgba({r},{g},{b},1.0)"
                    seg_x, seg_y, seg_z, seg_hover = [], [], [], []

                    for i, c in enumerate(cd):
                        if c in selected_set:
                            seg_x.append(trace.x[i])
                            seg_y.append(trace.y[i])
                            seg_z.append(trace.z[i])
                            seg_hover.append(trace.hovertext[i] if trace.hovertext else "")
                        else:
                            # None gap separates services in the trace
                            if seg_x:
                                seg_x.append(None)
                                seg_y.append(None)
                                seg_z.append(None)
                                seg_hover.append("")

                    # Strip trailing None gap
                    while seg_x and seg_x[-1] is None:
                        seg_x.pop(); seg_y.pop(); seg_z.pop(); seg_hover.pop()

                    if seg_x:
                        fig.add_trace(go.Scatter3d(
                            x=seg_x, y=seg_y, z=seg_z,
                            mode="lines+markers",
                            line=dict(color=bright_color, width=3),
                            marker=dict(size=3, color=bright_color),
                            hovertext=seg_hover,
                            hoverinfo="text",
                            name="__selected",
                            showlegend=False,
                        ))
            else:
                trace.opacity = 0.15 if selected_set else 1
                trace.hoverinfo = "skip" if selected_set else "text"

    def highlight_links(self, fig, selected_links):
        """
        Highlight one or more rake links in the visualization.

        Args:
            fig: Plotly figure object
            selected_links: Either a string (single link) or list of strings (multiple links)
        """
        if isinstance(selected_links, str):
            selected_links = [selected_links]

        selected_set = set(selected_links)

        for trace in fig.data:
            trace_link = trace.name.split("-")[0] if "-" in trace.name else trace.name

            if not selected_set:
                # Reset to original appearance
                trace.opacity = 1.0
                trace.hoverinfo = "text"
                if hasattr(trace, "marker"):
                    trace.marker.size = 2
            elif trace_link in selected_set:
                trace.opacity = 1.0
                trace.hoverinfo = "text"
                if hasattr(trace, "marker"):
                    trace.marker.size = 3
            else:
                trace.opacity = 0.05
                trace.hoverinfo = "skip"
                if hasattr(trace, "marker"):
                    trace.marker.size = 1

    def build_annotation(self, rc):
        return [
            dict(
                x=0.02,
                y=0.97,
                xref="paper",
                yref="paper",
                showarrow=False,
                align="left",
                bgcolor="rgba(0,0,0,0.75)",
                bordercolor="rgba(255,255,255,0.9)",
                borderwidth=2,
                borderpad=8,
                font=dict(size=14, color="white"),
                text=(
                    f"<b>Rake Link {rc.linkName}</b><br>"
                    f"Services: {len(rc.servicePath)}<br>"
                    f"Start: {rc.servicePath[0].initStation.name}<br>"
                    f"End: {rc.servicePath[-1].finalStation.name}<br>"
                    f"Distance: {int(rc.lengthKm)} km<br>"
                    f"Rake: {'AC' if rc.rake.isAC else 'Non-AC'} ({rc.rake.rakeSize}-car)<br>"
                ),
            )
        ]

    def reset_isolation(self, fig, wtt):
        for rc in wtt.rakecycles:
            rc.render = True
        fig.update_layout(annotations=[])
        for tr in fig.data:
            tr.opacity = 1.0
            if hasattr(tr, "line"):
                tr.line.width = 2
            if hasattr(tr, "marker"):
                tr.marker.size = 2
        return fig


from plotly.subplots import make_subplots


def _fmt_time(minutes: float) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h:02d}:{m:02d}"


def _time_axis_range(starts: list, gaps: list, pad: int = 30):
    ends = [s + g for s, g in zip(starts, gaps)]
    if starts:
        x_min = max(0,    min(starts) - pad)
        x_max = min(1440, max(ends)   + pad)
    else:
        x_min, x_max = 165, 1605
    tick_vals = list(range(int(x_min // 60) * 60, int(x_max) + 60, 60))
    tick_text  = [_fmt_time(v) for v in tick_vals]
    return x_min, x_max, tick_vals, tick_text


class StationWaitTimesChart:
    BAR_WIDTH       = 2
    AC_COLOR        = "#3b82f6"
    NONAC_COLOR     = "#94a3b8"
    CONVERTED_COLOR = "#000000"
    PRED_COLOR      = "#475569"

    def build(self, entry: dict) -> go.Figure:
        gaps_after    = entry.get("gaps", [])
        starts_after  = entry.get("gap_starts", [])
        rl_after      = entry.get("gap_rakelinkinfo",  ["?"] * len(gaps_after))
        svc_after     = entry.get("gap_serviceinfo",   ["?"] * len(gaps_after))
        gaps_before   = entry.get("gaps_before", [])
        starts_before = entry.get("gap_starts_before", [])
        rl_before     = entry.get("gap_rakelinkinfo_before", ["?"] * len(gaps_before))
        svc_before    = entry.get("gap_serviceinfo_before",  ["?"] * len(gaps_before))

        all_starts = starts_before + starts_after
        all_gaps   = gaps_before   + gaps_after
        x_min, x_max, tick_vals, tick_text = _time_axis_range(all_starts, all_gaps)
        ymax  = max(all_gaps, default=30) * 1.15

        brackets_before = entry.get("non_ac_brackets_before", [])
        brackets_after  = entry.get("non_ac_brackets_after",  [])
        y2max = max(
            [b["gap"] for b in brackets_before + brackets_after],
            default=30
        ) * 1.15

        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=["Before", "After"],
            shared_xaxes=True,
            vertical_spacing=0.14,
            specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
        )

        self._add_ac_bars(fig, 1, gaps_before, starts_before, rl_before, svc_before)
        self._add_nonac_brackets(fig, 1, brackets_before)
        self._add_ac_bars(fig, 2, gaps_after, starts_after, rl_after, svc_after)
        self._add_nonac_brackets_after(fig, 2, brackets_after, brackets_before)
        self._apply_layout(fig, entry, x_min, x_max, tick_vals, tick_text, ymax, y2max)
        return fig

    def _add_ac_bars(self, fig, row, gaps, starts, rl, svc):
        if not gaps or not starts:
            fig.add_trace(go.Bar(x=[], y=[], showlegend=False),
                          row=row, col=1, secondary_y=False)
            return
        x = [s + g for s, g in zip(starts, gaps)]
        fig.add_trace(go.Bar(
            x=x, y=gaps,
            width=self.BAR_WIDTH,
            marker_color=self.AC_COLOR,
            showlegend=False,
            hovertemplate=(
                "%{customdata[0]}<br>"
                "Rakelink: %{customdata[1]}<br>"
                "Service: %{customdata[2]}<br>"
                "Gap from prev: %{y} min<extra></extra>"
            ),
            customdata=[[_fmt_time(xi), r, s] for xi, r, s in zip(x, rl, svc)],
        ), row=row, col=1, secondary_y=False)

    def _add_nonac_brackets(self, fig, row, brackets):
        if not brackets:
            return
        colors  = [self.CONVERTED_COLOR if b["is_converted"] else self.NONAC_COLOR
                   for b in brackets]
        labels  = ["(Converted to AC)" if b["is_converted"] else "Non-AC"
                   for b in brackets]
        fig.add_trace(go.Bar(
            x=[b["time"] for b in brackets],
            y=[b["gap"]  for b in brackets],
            width=self.BAR_WIDTH,
            marker_color=colors,
            showlegend=False,
            hovertemplate=(
                "%{customdata[0]}<br>%{customdata[1]}<br>"
                "Rakelink: %{customdata[2]}<br>"
                "Service: %{customdata[3]}<br>"
                "Gap from prev: %{y} min<extra></extra>"
            ),
            customdata=[
                [_fmt_time(b["time"]), lbl, b.get("rakelink", "?"), b.get("service_id", "?")]
                for b, lbl in zip(brackets, labels)
            ],
        ), row=row, col=1, secondary_y=True)

    def _add_nonac_brackets_after(self, fig, row, brackets_after, brackets_before):
        if not brackets_after:
            return

        bx    = [b["time"] for b in brackets_after]
        by    = [b["gap"]  for b in brackets_after]
        bprev = [b.get("prev_time", t - g) for b, t, g in zip(brackets_after, bx, by)]

        fig.add_trace(go.Bar(
            x=bx, y=by,
            width=self.BAR_WIDTH,
            marker_color=self.NONAC_COLOR,
            showlegend=False,
            hovertemplate=(
                "%{customdata[0]}<br>"
                "Non-AC (gap widened by conversion)<br>"
                "Rakelink: %{customdata[1]}<br>"
                "Service: %{customdata[2]}<br>"
                "Gap from prev: %{y} min<extra></extra>"
            ),
            customdata=[
                [_fmt_time(b["time"]), b.get("rakelink", "?"), b.get("service_id", "?")]
                for b in brackets_after
            ],
        ), row=row, col=1, secondary_y=True)

        for t, p, g in zip(bx, bprev, by):
            fig.add_shape(
                type="line", x0=p, x1=t, y0=g, y1=g,
                line=dict(color=self.NONAC_COLOR, width=1, dash="dot"),
                row=row, col=1, secondary_y=True,
            )

        before_by_time = {b["time"]: b for b in brackets_before}
        widened_times  = set(bx)
        seen           = set()
        pred_bx, pred_by, pred_cd = [], [], []

        for b in brackets_after:
            pt = b.get("prev_time")
            if pt is None or pt in seen or pt in widened_times:
                continue
            src = before_by_time.get(pt)
            if src:
                seen.add(pt)
                pred_bx.append(src["time"])
                pred_by.append(src["gap"])
                pred_cd.append([_fmt_time(src["time"]),
                                 src.get("rakelink", "?"),
                                 src.get("service_id", "?")])

        if pred_bx:
            fig.add_trace(go.Bar(
                x=pred_bx, y=pred_by,
                width=self.BAR_WIDTH,
                marker_color=self.PRED_COLOR,
                opacity=0.75,
                showlegend=False,
                hovertemplate=(
                    "%{customdata[0]}<br>"
                    "Non-AC (preceding event)<br>"
                    "Rakelink: %{customdata[1]}<br>"
                    "Service: %{customdata[2]}<br>"
                    "Gap from prev: %{y} min<extra></extra>"
                ),
                customdata=pred_cd,
            ), row=row, col=1, secondary_y=True)

    def _apply_layout(self, fig, entry, x_min, x_max, tick_vals, tick_text, ymax, y2max):
        fig.update_xaxes(
            range=[x_min, x_max],
            tickvals=tick_vals, ticktext=tick_text,
            showgrid=True, gridcolor="#e2e8f0",
        )
        fig.update_yaxes(
            range=[0, ymax], dtick=20, tick0=0,
            title_text="Minutes",
            title_font=dict(color=self.AC_COLOR),
            tickfont=dict(color=self.AC_COLOR),
            showgrid=True, gridcolor="#e2e8f0",
            secondary_y=False,
        )
        for row in (1, 2):
            fig.update_yaxes(
                range=[0, y2max],
                title_text="Non-AC gap (min)",
                title_font=dict(color=self.NONAC_COLOR),
                tickfont=dict(color=self.NONAC_COLOR),
                showgrid=False,
                secondary_y=True, row=row, col=1,
            )
        fig.update_xaxes(title_text="Time of day", row=2, col=1)
        fig.update_layout(
            height=560,
            margin=dict(l=50, r=20, t=40, b=40),
            paper_bgcolor="white", plot_bgcolor="white",
            font=dict(size=11),
            bargap=0,
            yaxis3=dict(matches="y"),
            yaxis4=dict(matches="y2"),
            title=dict(
                text=f"{entry['station']} ({entry['direction']})",
                font=dict(size=12), x=0.5,
            ),
        )


class ACDensityChart:
    def build(self, density: dict) -> go.Figure:
        stations = density["stations"]
        buckets  = density["buckets"]

        def make_z(data):
            return [[data[s].get(b, 0) for b in buckets] for s in stations]

        z_before    = make_z(density["before"])
        z_after     = make_z(density["after"])
        all_vals    = [v for row in z_before + z_after for v in row]
        zmin_shared = min(all_vals, default=0)
        zmax_shared = max(all_vals, default=1)

        fig = make_subplots(rows=1, cols=2,
                            subplot_titles=["Before", "After"],
                            horizontal_spacing=0.08)
        fig.add_trace(go.Heatmap(
            z=z_before, x=buckets, y=stations,
            colorscale="Blues", showscale=False,
            zmin=zmin_shared, zmax=zmax_shared,
        ), row=1, col=1)
        fig.add_trace(go.Heatmap(
            z=z_after, x=buckets, y=stations,
            colorscale="Blues", showscale=True,
            colorbar=dict(title="Services", len=0.8),
            zmin=zmin_shared, zmax=zmax_shared,
        ), row=1, col=2)
        fig.update_layout(
            height=max(200, len(stations) * 18 + 60),
            margin=dict(l=100, r=40, t=30, b=30),
            paper_bgcolor="white", plot_bgcolor="white",
            font=dict(size=11),
        )
        return fig


class LinkFollowingsChart:
    def build(self, fol: dict) -> go.Figure:
        nodes       = fol["nodes"]
        ac_pair_set = {tuple(p) for p in fol.get("ac_ac_pairs", [])}
        z, annotations = self._build_matrix(nodes, fol["matrix"], ac_pair_set)

        fig = go.Figure(go.Heatmap(
            z=z, x=nodes, y=nodes,
            colorscale="Viridis", showscale=True,
            colorbar=dict(title="Weight", len=0.8),
        ))
        fig.update_layout(
            height=max(250, len(nodes) * 22 + 60),
            margin=dict(l=80, r=40, t=10, b=60),
            paper_bgcolor="white", plot_bgcolor="white",
            font=dict(size=10),
            annotations=annotations,
            xaxis=dict(tickangle=-45),
        )
        return fig

    def _build_matrix(self, nodes, matrix, ac_pair_set):
        z, annotations = [], []
        for i, row_node in enumerate(nodes):
            row_vals = []
            for j, col_node in enumerate(nodes):
                if i == j:
                    row_vals.append(0)
                else:
                    pair = tuple(sorted([row_node, col_node]))
                    w = matrix.get(pair, 0)
                    row_vals.append(w)
                    if pair in ac_pair_set and w > 0:
                        annotations.append(dict(
                            x=j, y=i, text="*", showarrow=False,
                            font=dict(color="red", size=10),
                        ))
            z.append(row_vals)
        return z, annotations
