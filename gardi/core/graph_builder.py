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

        for rc in rakecycles:
            # svc mode: Only render filtered services
            if is_service_filter:
                for svc in rc.servicePath:
                    if not svc.render:
                        continue

                    x_in, y_in, z_in, labels_in = [], [], [], []
                    x_out, y_out, z_out, labels_out = [], [], [], []

                    for ev in svc.events:
                        minutes = ev.atTime

                        stName = str(ev.atStation).strip().upper()
                        if stName not in stationToY:
                            continue

                        x_in.append(minutes)
                        y_in.append(stationToY[stName])
                        z_in.append(z_offset)
                        labels_in.append(stName)

                    # Format sids
                    svc_id_str = (
                        ",".join(str(sid) for sid in svc.serviceId)
                        if svc.serviceId
                        else "?"
                    )

                    # dim out-of-range events
                    if x_out:
                        color_dim = (
                            "rgba(66,133,244,0.6)"
                            if svc.needsACRake
                            else "rgba(90,90,90,0.6)"
                        )

                        all_traces.append(
                            go.Scatter3d(
                                x=x_out,
                                y=y_out,
                                z=z_out,
                                mode="lines+markers",
                                line=dict(color=color_dim),
                                marker=dict(size=2, color=color_dim),
                                hovertext=[
                                    f"{svc_id_str}: {st} @ {(int(xx)//60) % 24:02d}:{int(xx%60):02d} (outside filter)"
                                    for xx, st in zip(x_out, labels_out)
                                ],
                                hoverinfo="text",
                                name=f"{rc.linkName}-{svc_id_str} (context)",
                                showlegend=False,
                                visible=True,
                            )
                        )

                    # render in-range events
                    if x_in:
                        color_bright = (
                            "rgba(66,133,244,0.8)"
                            if svc.needsACRake
                            else "rgba(90,90,90,0.8)"
                        )

                        all_traces.append(
                            go.Scatter3d(
                                x=x_in,
                                y=y_in,
                                z=z_in,
                                mode="lines+markers",
                                line=dict(color=color_bright),
                                marker=dict(
                                    size=2, color=color_bright
                                ),
                                hovertext=[
                                    f"{svc_id_str}: {st} @ {(int(xx)//60) % 24:02d}:{int(xx%60):02d}"
                                    for xx, st in zip(x_in, labels_in)
                                ],
                                hoverinfo="text",
                                name=f"{rc.linkName}-{svc_id_str}",
                                visible=True,
                            )
                        )
                        z_labels.append((z_offset, f"{rc.linkName}-{svc_id_str}"))

                    # Only increment z if we rendered something
                    if x_in or x_out:
                        z_offset += 40

            # rakelink mode
            else:
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
                    title="Time of Day →",
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
            width=1300,
            height=700,
            margin=dict(t=0, l=5, b=5, r=5),
            autosize=True,
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
        """
        Highlight selected services in the visualization.

        Args:
            fig: Plotly figure object
            selected_services: List of service ID strings (e.g., ["93001", "93002"])
        """
        if not selected_services:
            return

        selected_set = set(selected_services)

        for trace in fig.data:
            if "-" in trace.name:
                trace_service = trace.name.split("-")[1]

                if trace_service in selected_set:
                    trace.opacity = 1.0
                    if hasattr(trace, "marker"):
                        trace.marker.size = 3
                else:
                    trace.opacity = 0.35
                    if hasattr(trace, "marker"):
                        trace.marker.size = 1
            else:
                trace.opacity = 0.35

    def highlight_links(self, fig, selected_links):
        """
        Highlight one or more rake links in the visualization.

        Args:
            fig: Plotly figure object
            selected_links: Either a string (single link) or list of strings (multiple links)
        """
        if isinstance(selected_links, str):
            selected_links = [selected_links]

        if not selected_links:
            return

        selected_set = set(selected_links)

        for trace in fig.data:
            trace_link = trace.name.split("-")[0] if "-" in trace.name else trace.name

            if trace_link in selected_set:
                trace.opacity = 1.0
                if hasattr(trace, "marker"):
                    trace.marker.size = 3
            else:
                trace.opacity = 0.35
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
