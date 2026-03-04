#!/usr/bin/env python3

import plotly.graph_objs as go
from gardi.core.filters import FilterType
from gardi.core.models import DISTANCE_MAP
from gardi.core import utils


class GraphBuilder:
    def build_figure(self, wtt, query, distance_map=None):
        if distance_map is None:
            distance_map = DISTANCE_MAP

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
                    if not svc.render:
                        z_offset += 40
                        continue

                    svc_id_str = (
                        ",".join(str(sid) for sid in svc.serviceId)
                        if svc.serviceId
                        else "?"
                    )
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
                if not rc.render:
                    continue

                if query.type == FilterType.STATION:
                    mode = "markers"
                elif query.type == FilterType.RAKELINK:
                    mode = "lines+markers"

                # enumerate rakelink events
                x, y, z, stationLabels = [], [], [], []

                for svc in rc.servicePath:
                    if not svc.render:
                        continue
                    for ev in svc.events:
                        if not ev.atTime or not ev.atStation:
                            continue

                        if not ev.render:
                            continue

                        minutes = ev.atTime

                        stName = str(ev.atStation).strip().upper()
                        if stName not in stationToY:
                            continue

                        x.append(minutes)
                        y.append(stationToY[stName])
                        z.append(z_offset)
                        stationLabels.append(stName)

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
                                f"{rc.linkName}: {st} @ {(int(xx)//60) % 24:02d}:{int(xx%60):02d}"
                                for xx, st in zip(x, stationLabels)
                            ],
                            hoverinfo="text",
                            name=rc.linkName,
                            meta={"ac": rc.rake.isAC},
                            visible=True,
                        )
                    )
                    z_labels.append((z_offset, rc.linkName))
                    z_offset += 40

        if query.inTimePeriod and (
            query.type == FilterType.SERVICE
            or query.type == FilterType.STATION
        ):
            x_start, x_end = query.inTimePeriod
            x_end += 90  # padding
        else:
            x_start, x_end = 165, 1605

        tickPositions = list(range(x_start, x_end + 1, 120))
        tickLabels = [f"{(t // 60) % 24:02d}:{int(t % 60):02d}" for t in tickPositions]

        yTickVals = list(stationToY.values())
        yTickText = list(stationToY.keys())

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
            updatemenus=[dict(
                type="buttons",
                buttons=[
                    dict(label="Front", method="relayout", args=[{
                        "scene.camera.eye": {"x": 0, "y": 0, "z": 2.5},
                        "scene.camera.up": {"x": 0, "y": 1, "z": 0},
                    }]),
                    dict(label="Top", method="relayout", args=[{
                        "scene.camera.eye": {"x": 0, "y": 2.5, "z": 0},
                        "scene.camera.up": {"x": 0, "y": 1, "z": 0},
                    }]),
                ],
                direction="left",
                showactive=True,
                x=0.0,
                y=1.05,
                bgcolor="rgba(40,40,40,0.8)",
                font=dict(color="#CCCCCC"),
            )],
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

    def post_process_station_mode(self, fig, query, wtt, parser):
        if query.type != FilterType.STATION:
            return fig

        fig.update_layout(
            scene_camera=dict(eye=dict(x=0, y=0, z=1.5)),
            scene=dict(aspectratio=dict(x=3, y=1.5, z=1.2)),
        )

        for i, rc in enumerate(wtt.rakecycles):
            for svc in rc.servicePath:
                if i < len(wtt.rakecycles) / 2 + 10:
                    svc.needsACRake = True

        before = utils.corridorMixingMinimal(
            query.startStation, query.endStation, query.inTimePeriod[0], query.inTimePeriod[1],
            parser.eventsByStationMap, parser.distanceMap
        )
        after = utils.corridorMixingMinimal(
            query.startStation, query.endStation, query.inTimePeriod[0], query.inTimePeriod[1],
            parser.eventsByStationMap, parser.distanceMap
        )

        print("=== Mixing Report ===")
        for b, a in zip(before, after):
            print(f"{b['station']}: {b['mixing_score']:.3f} -> {a['mixing_score']:.3f}")

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
                else:
                    # Dim the entire original trace
                    dim_color = f"rgba({r},{g},{b},0.05)"
                    trace.marker.color = dim_color
                    trace.marker.size = 1
                    trace.marker.opacity = 1
                    trace.line.color = dim_color

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

    def highlight_stations(self, fig, station_names):
        """Highlight events at selected stations, dim everything else.

        Zooms both Y-axis (distance) and X-axis (time) to the selected stations.
        """
        st_set = {s.strip().upper() for s in station_names}
        matched_times = []

        for trace in fig.data:
            if trace.name == "__focus":
                continue  # preserve focus rings
            hover = trace.hovertext
            if hover is None or len(hover) == 0:
                trace.opacity = 0.15
                continue

            # Scatter3d marker.opacity is scalar only, so use per-point
            # color with alpha to achieve per-point dimming
            sizes = []
            colors = []
            # Determine color from trace meta
            is_ac = isinstance(trace.meta, dict) and trace.meta.get("ac", False)
            if is_ac:
                r, g, b = 66, 133, 244
            else:
                r, g, b = 90, 90, 90

            x_vals = trace.x if trace.x is not None else []
            for i, h in enumerate(hover):
                if h and any(st in h.upper() for st in st_set):
                    sizes.append(5)
                    colors.append(f"rgba({r},{g},{b},1.0)")
                    if i < len(x_vals) and x_vals[i] is not None:
                        matched_times.append(x_vals[i])
                else:
                    sizes.append(1)
                    colors.append(f"rgba({r},{g},{b},0.07)")

            trace.marker.size = sizes
            trace.marker.color = colors
            trace.line.color = f"rgba({r},{g},{b},0.05)"

        # Zoom Y-axis to selected stations' distance range
        dists = [DISTANCE_MAP[st] for st in st_set if st in DISTANCE_MAP]
        if dists:
            y_min = min(dists)
            y_max = max(dists)
            pad = max(3, (y_max - y_min) * 0.15)
            fig.update_layout(scene_yaxis_range=[y_min - pad, y_max + pad])

        # Zoom X-axis to time range of matched events
        if matched_times:
            x_min = min(matched_times)
            x_max = max(matched_times)
            x_pad = max(15, (x_max - x_min) * 0.05)
            x_start = x_min - x_pad
            x_end = x_max + x_pad
            tick_step = 60 if (x_end - x_start) < 600 else 120
            ticks = list(range(int(x_start) - int(x_start) % tick_step, int(x_end) + tick_step, tick_step))
            tick_labels = [f"{(t // 60) % 24:02d}:{t % 60:02d}" for t in ticks]
            fig.update_layout(
                scene_xaxis_range=[x_start, x_end],
                scene_xaxis_tickvals=ticks,
                scene_xaxis_ticktext=tick_labels,
            )

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
                if hasattr(trace, "marker"):
                    trace.marker.size = 2
            elif trace_link in selected_set:
                trace.opacity = 1.0
                if hasattr(trace, "marker"):
                    trace.marker.size = 3
            else:
                trace.opacity = 0.05
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

    def focus_event(self, fig, targets):
        """Add circle-open overlay(s) on specific event(s) and zoom X-axis.

        Args:
            fig: Plotly figure
            targets: list of (time_raw, station_name) tuples
        """
        if not targets:
            return

        matched_points = []
        for time_raw, station_name in targets:
            st_upper = station_name.strip().upper()
            for trace in fig.data:
                if trace.name == "__focus":
                    continue
                hover = trace.hovertext
                if hover is None or len(hover) == 0:
                    continue
                x_vals = trace.x if trace.x is not None else []
                y_vals = trace.y if trace.y is not None else []
                z_vals = trace.z if trace.z is not None else []
                found = False
                for i, h in enumerate(hover):
                    if h is None or i >= len(x_vals) or x_vals[i] is None:
                        continue
                    if st_upper in str(h).upper() and abs(x_vals[i] - time_raw) < 1.0:
                        matched_points.append((x_vals[i], y_vals[i], z_vals[i]))
                        found = True
                        break
                if found:
                    break

        if not matched_points:
            return

        # Remove existing focus trace
        fig.data = [t for t in fig.data if t.name != "__focus"]

        fig.add_trace(go.Scatter3d(
            x=[p[0] for p in matched_points],
            y=[p[1] for p in matched_points],
            z=[p[2] for p in matched_points],
            mode="markers",
            marker=dict(
                size=14,
                symbol="circle-open",
                color="rgba(255,255,255,0.85)",
                line=dict(width=2, color="rgba(255,255,255,0.85)"),
            ),
            name="__focus",
            showlegend=False,
            hoverinfo="skip",
        ))

        # Zoom X-axis to encompass all matched events +/-30min
        x_times = [p[0] for p in matched_points]
        x_start = min(x_times) - 30
        x_end = max(x_times) + 30
        tick_step = 10
        ticks = list(range(int(x_start) - int(x_start) % tick_step, int(x_end) + tick_step, tick_step))
        tick_labels = [f"{(t // 60) % 24:02d}:{t % 60:02d}" for t in ticks]
        fig.update_layout(
            scene_xaxis_range=[x_start, x_end],
            scene_xaxis_tickvals=ticks,
            scene_xaxis_ticktext=tick_labels,
        )

    def reset_station_highlight(self, fig):
        """Reset all traces to default appearance, remove focus overlay."""
        # Remove focus trace
        fig.data = [t for t in fig.data if t.name != "__focus"]

        for trace in fig.data:
            hover = trace.hovertext
            if hover is None or len(hover) == 0:
                trace.opacity = 1.0
                continue

            # Determine original color from trace meta
            is_ac = isinstance(trace.meta, dict) and trace.meta.get("ac", False)
            if is_ac:
                r, g, b = 66, 133, 244
            else:
                r, g, b = 90, 90, 90

            color = f"rgba({r},{g},{b},0.8)"
            trace.marker.size = 2
            trace.marker.color = color
            trace.line.color = color

        # Reset axis ranges to original build-time values stored in layout.meta
        meta = fig.layout.meta if isinstance(fig.layout.meta, dict) else {}
        x_range = meta.get("x_range", [165, 1605])
        x_ticks = meta.get("x_tickvals", list(range(165, 1606, 120)))
        x_labels = meta.get("x_ticktext", [f"{(t // 60) % 24:02d}:{t % 60:02d}" for t in range(165, 1606, 120)])
        y_range = meta.get("y_range", [min(DISTANCE_MAP.values()), max(DISTANCE_MAP.values())])

        fig.update_layout(
            scene_xaxis_range=x_range,
            scene_xaxis_tickvals=x_ticks,
            scene_xaxis_ticktext=x_labels,
            scene_yaxis_range=y_range,
        )

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
