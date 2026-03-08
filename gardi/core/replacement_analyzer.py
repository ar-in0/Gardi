"""Replacement set analysis for AC rake procurement decisions.

Analyzer methods return structured data (dicts, dataclasses).
format_report() provides thin CLI formatting.
exportReportXlsx() produces structured XLSX output.
"""

import io
from collections import defaultdict
from dataclasses import dataclass, field

import pandas as pd

from gardi.core.data_builder import fmt_time
from gardi.core.models import (
    DISTANCE_MAP, Direction, EventType, Line,
)

STATIONS_ORDERED = sorted(DISTANCE_MAP.keys(), key=lambda s: DISTANCE_MAP[s])

# Peak windows (minutes since midnight)
PEAK_MORNING = (480, 660)   # 08:00-11:00
PEAK_EVENING = (1020, 1230) # 17:00-20:30


@dataclass
class ArrivalEntry:
    """One arrival at a station in a given direction."""
    station: str
    time: float               # minutes since midnight
    service_id: str
    rakelink: str
    is_ac: bool               # AC state after conversion
    originally_ac: bool       # AC state before conversion
    direction: str            # "UP" or "DOWN"


@dataclass
class RakeLinkProfile:
    name: str
    depot_start: str
    depot_end: str
    length_km: float
    duration_minutes: float
    n_services: int
    line_types: set
    stations_served: list
    is_ac: bool


@dataclass
class ReplacementReport:
    """Bundle of all analysis results for a replacement set."""
    replacement_set: list
    depot: dict
    semi_fast: dict
    coverage: dict
    followings: dict
    profiles: dict                    # link name -> RakeLinkProfile
    station_arrivals: list = None     # ArrivalEntry list if station specified
    beforeAfterMetrics: dict = None   # before/after AC service metrics
    headwayGaps: list = None          # AC headway gaps by station
    acDensityByTod: dict = None       # AC density by time-of-day


class ReplacementAnalyzer:
    """Analyzes the impact of converting a set of rakelinks to AC."""

    def __init__(self, wtt, parser):
        self.wtt = wtt

        # rakelink name -> RakeCycle
        self.rc_by_name = {}
        # service_id (str) -> rakelink name
        self.svc_to_link = {}
        # rakelink name -> RakeLinkProfile
        self.profiles = {}

        self._index_rakelinks()
        self._build_profiles()

    def _index_rakelinks(self):
        for rc in self.wtt.rakecycles:
            self.rc_by_name[rc.linkName] = rc
            if rc.servicePath:
                for svc in rc.servicePath:
                    for sid in svc.serviceId:
                        self.svc_to_link[str(sid)] = rc.linkName

    def _build_profiles(self):
        for rc in self.wtt.rakecycles:
            if not rc.servicePath or not rc.servicePath[0].events:
                continue

            first_svc = rc.servicePath[0]
            last_svc = rc.servicePath[-1]
            depot_start = first_svc.events[0].atStation if first_svc.events else "?"
            depot_end = last_svc.events[-1].atStation if last_svc.events else "?"

            line_types = set()
            for svc in rc.servicePath:
                if svc.line:
                    line_types.add(svc.line)
            stations = list(dict.fromkeys(
                evt.atStation for svc in rc.servicePath for evt in svc.events
            ))

            is_ac = rc.rake.isAC if rc.rake else False

            self.profiles[rc.linkName] = RakeLinkProfile(
                name=rc.linkName,
                depot_start=depot_start,
                depot_end=depot_end,
                length_km=round(rc.lengthKm, 1),
                duration_minutes=round(rc.durationMinutes, 1),
                n_services=len(rc.servicePath),
                line_types=line_types,
                stations_served=stations,
                is_ac=is_ac,
            )

    def build_station_sequences(self, replacement_set: set):
        """For each (station, direction), build time-ordered arrival list.

        Services belonging to replacement_set are marked is_ac=True.
        Only includes stations present in DISTANCE_MAP.
        """
        by_station = defaultdict(list)

        services = self.wtt.suburbanServices or (self.wtt.upServices + self.wtt.downServices)
        for svc in services:
            if not svc.events or len(svc.events) < 2:
                continue
            direction = svc.direction.name if svc.direction else "UNKNOWN"
            sid = str(svc.serviceId[0]) if svc.serviceId else "?"
            rakelink = self.svc_to_link.get(sid, "?")

            originally_ac = svc.needsACRake
            is_ac = originally_ac or (rakelink in replacement_set)
            seen_stations = set()
            for evt in svc.events:
                if evt.atStation not in DISTANCE_MAP:
                    continue
                if evt.eType == EventType.ARRIVAL and evt.atTime is not None:
                    if evt.atStation not in seen_stations:
                        seen_stations.add(evt.atStation)
                        by_station[(evt.atStation, direction)].append(ArrivalEntry(
                            station=evt.atStation,
                            time=evt.atTime,
                            service_id=sid,
                            rakelink=rakelink,
                            is_ac=is_ac,
                            originally_ac=originally_ac,
                            direction=direction,
                        ))

        for key in by_station:
            by_station[key].sort(key=lambda e: e.time)

        return by_station

    def build_followings_graph(self, by_station):
        """Rakelink followings graph: edge (A, B) weighted by how many times
        a service from link A is immediately followed by one from link B
        at any station+direction."""
        edges = defaultdict(int)
        for (station, direction), arrivals in by_station.items():
            for i in range(len(arrivals) - 1):
                cur, nxt = arrivals[i], arrivals[i+1]
                if cur.rakelink != "?" and nxt.rakelink != "?" and cur.rakelink != nxt.rakelink:
                    pair = tuple(sorted([cur.rakelink, nxt.rakelink]))
                    edges[pair] += 1
        return dict(edges)

    def depot_compatibility(self, replacement_set):
        """Identify self-loops and replaceable pairs within the set.

        Self-loop: link where depot_start == depot_end (one AC rake repeats daily).
        Replaceable pair: (A, B) where A.end == B.start AND B.end == A.start
        (two AC rakes swap overnight).
        """
        profiles = [self.profiles[name] for name in replacement_set if name in self.profiles]

        links = []
        for p in profiles:
            links.append({
                "name": p.name,
                "depot_start": p.depot_start,
                "depot_end": p.depot_end,
                "is_ac": p.is_ac,
            })

        self_loops = [p.name for p in profiles if p.depot_start == p.depot_end]

        paired = set()
        pairs = []
        for i, src in enumerate(profiles):
            if src.name in paired:
                continue
            for j, dst in enumerate(profiles):
                if i != j and dst.name not in paired:
                    if src.depot_end == dst.depot_start and dst.depot_end == src.depot_start:
                        pairs.append((src.name, dst.name, src.depot_end, dst.depot_end))
                        paired.add(src.name)
                        paired.add(dst.name)
                        break

        matched = set(self_loops) | paired
        unmatched = [p.name for p in profiles if p.name not in matched]

        return {
            "links": links,
            "self_loops": self_loops,
            "pairs": pairs,
            "unmatched": unmatched,
        }

    def semi_fast_check(self, replacement_set):
        """Link -> list of semi-fast service IDs."""
        result = {}
        for name in replacement_set:
            rc = self.rc_by_name.get(name)
            semi_fast = []
            if rc and rc.servicePath:
                for svc in rc.servicePath:
                    if svc.line == Line.SEMI_FAST or len(set(m[1] for m in svc.lineSwitches)) > 1:
                        semi_fast.extend(str(s) for s in svc.serviceId)
            result[name] = semi_fast
        return result

    def coverage_matrix(self, replacement_set, by_station):
        """Station x rakelink service count matrix.

        Only includes stations from DISTANCE_MAP, ordered by corridor distance.
        """
        rset = set(replacement_set)
        matrix = defaultdict(lambda: defaultdict(int))
        seen = defaultdict(lambda: defaultdict(set))

        for (station, direction), arrivals in by_station.items():
            for a in arrivals:
                if a.rakelink in rset and a.service_id not in seen[station][a.rakelink]:
                    seen[station][a.rakelink].add(a.service_id)
                    matrix[station][a.rakelink] += 1

        stations = sorted(matrix.keys(), key=lambda s: DISTANCE_MAP.get(s, 999))

        return {
            "stations": stations,
            "links": list(replacement_set),
            "matrix": {s: dict(matrix[s]) for s in stations},
        }

    def followings_matrix(self, replacement_set, edges):
        """Followings matrix scoped to replacement set + their neighbors."""
        rset = set(replacement_set)

        neighbors = set()
        for (link_a, link_b) in edges:
            if link_a in rset:
                neighbors.add(link_b)
            if link_b in rset:
                neighbors.add(link_a)

        nodes = sorted(rset | neighbors)

        node_set = set(nodes)
        filtered_edges = {}
        for (link_a, link_b), weight in edges.items():
            if link_a in node_set and link_b in node_set:
                filtered_edges[(link_a, link_b)] = weight

        ac_links = set()
        for name in nodes:
            p = self.profiles.get(name)
            if p and (p.is_ac or name in rset):
                ac_links.add(name)

        ac_pairs = []
        ac_pair_weight = 0
        for (link_a, link_b), weight in filtered_edges.items():
            if link_a in ac_links and link_b in ac_links:
                ac_pairs.append((link_a, link_b))
                ac_pair_weight += weight

        return {
            "nodes": nodes,
            "matrix": filtered_edges,
            "ac_ac_pairs": ac_pairs,
            "total_ac_ac_followings": ac_pair_weight,
        }

    def computeBeforeAfterMetrics(self, by_station, replacement_set):
        """Compute before/after AC service metrics.

        Returns {"before": {...}, "after": {...}, "delta": {...}}
        """
        rset = set(replacement_set)
        all_arrivals = [a for arrivals in by_station.values() for a in arrivals]

        # Unique services (by service_id)
        before_ac_svcs = set()
        after_ac_svcs = set()
        total_svcs = set()
        for a in all_arrivals:
            total_svcs.add(a.service_id)
            if a.originally_ac:
                before_ac_svcs.add(a.service_id)
            if a.is_ac:
                after_ac_svcs.add(a.service_id)

        total = len(total_svcs)

        # Per-station AC coverage (fraction of arrivals that are AC)
        station_before = defaultdict(lambda: {"ac": 0, "total": 0})
        station_after = defaultdict(lambda: {"ac": 0, "total": 0})
        for a in all_arrivals:
            station_before[a.station]["total"] += 1
            station_after[a.station]["total"] += 1
            if a.originally_ac:
                station_before[a.station]["ac"] += 1
            if a.is_ac:
                station_after[a.station]["ac"] += 1

        def pct(d):
            return {s: round(v["ac"] / v["total"] * 100, 1) if v["total"] > 0 else 0
                    for s, v in d.items()}

        # Peak-hour AC frequency at top stations
        def peak_ac_count(arrivals, use_after=False):
            counts = defaultdict(int)
            for a in arrivals:
                is_peak = any(lo <= a.time <= hi for lo, hi in [PEAK_MORNING, PEAK_EVENING])
                if not is_peak:
                    continue
                ac = a.is_ac if use_after else a.originally_ac
                if ac:
                    counts[a.station] += 1
            return dict(counts)

        before = {
            "ac_services": len(before_ac_svcs),
            "ac_pct": round(len(before_ac_svcs) / total * 100, 1) if total else 0,
            "station_ac_pct": pct(station_before),
            "peak_ac_frequency": peak_ac_count(all_arrivals, use_after=False),
        }
        after = {
            "ac_services": len(after_ac_svcs),
            "ac_pct": round(len(after_ac_svcs) / total * 100, 1) if total else 0,
            "station_ac_pct": pct(station_after),
            "peak_ac_frequency": peak_ac_count(all_arrivals, use_after=True),
        }
        delta = {
            "ac_services": after["ac_services"] - before["ac_services"],
            "ac_pct": round(after["ac_pct"] - before["ac_pct"], 1),
        }
        return {"before": before, "after": after, "delta": delta, "total_services": total}

    def computeACHeadwayGaps(self, by_station, replacement_set, thresholdMinutes=15):
        """Compute AC headway gaps per (station, direction).

        Returns list of {"station", "direction", "gaps", "maxGap", "meanGap", "count"}
        sorted by worst gap descending.
        """
        results = []
        for (station, direction), arrivals in by_station.items():
            ac_arrivals = [a for a in arrivals if a.is_ac]
            if len(ac_arrivals) < 2:
                continue

            gaps = []
            for i in range(len(ac_arrivals) - 1):
                gap = ac_arrivals[i + 1].time - ac_arrivals[i].time
                if gap > 0:
                    gaps.append(round(gap, 1))

            if not gaps:
                continue

            results.append({
                "station": station,
                "direction": direction,
                "gaps": gaps,
                "maxGap": max(gaps),
                "meanGap": round(sum(gaps) / len(gaps), 1),
                "count": len(gaps),
                "exceedances": sum(1 for g in gaps if g >= thresholdMinutes),
            })

        results.sort(key=lambda r: -r["maxGap"])
        return results

    def computeACDensityByTimeOfDay(self, by_station, replacement_set, bucketMinutes=60):
        """Compute station x time-bucket matrix of AC service counts.

        Returns {"stations", "buckets", "before", "after"} where before/after are
        {station: {bucket_label: count}} dicts.
        """
        n_buckets = 1440 // bucketMinutes
        bucket_labels = []
        for i in range(n_buckets):
            start_m = i * bucketMinutes
            bucket_labels.append(f"{start_m // 60:02d}:{start_m % 60:02d}")

        stations = sorted(
            set(a.station for arrivals in by_station.values() for a in arrivals),
            key=lambda s: DISTANCE_MAP.get(s, 999),
        )

        before = {s: {b: 0 for b in bucket_labels} for s in stations}
        after = {s: {b: 0 for b in bucket_labels} for s in stations}

        for (station, _direction), arrivals in by_station.items():
            for a in arrivals:
                bucket_idx = min(int(a.time // bucketMinutes), n_buckets - 1)
                bl = bucket_labels[bucket_idx]
                if a.originally_ac:
                    before[station][bl] += 1
                if a.is_ac:
                    after[station][bl] += 1

        return {
            "stations": stations,
            "buckets": bucket_labels,
            "before": before,
            "after": after,
        }

    def station_sequence(self, station, direction, by_station, time_windows=None):
        """Return raw arrival sequence at a station, optionally filtered to time windows."""
        results = []
        for d in (["UP", "DOWN"] if direction is None else [direction]):
            arrivals = by_station.get((station, d), [])
            if time_windows:
                arrivals = [a for a in arrivals
                            if any(lo <= a.time <= hi for lo, hi in time_windows)]
            results.extend(arrivals)

        results.sort(key=lambda e: e.time)
        return results

    def evaluate(self, replacement_set, peak_only=False, station=None):
        """Run full analysis and return structured report."""
        rset = set(replacement_set)
        by_station = self.build_station_sequences(rset)
        edges = self.build_followings_graph(by_station)

        depot = self.depot_compatibility(replacement_set)
        semi_fast = self.semi_fast_check(replacement_set)
        coverage = self.coverage_matrix(replacement_set, by_station)
        followings = self.followings_matrix(replacement_set, edges)

        profiles = {name: self.profiles[name] for name in replacement_set if name in self.profiles}

        # Enriched analysis
        before_after = self.computeBeforeAfterMetrics(by_station, replacement_set)
        headway_gaps = self.computeACHeadwayGaps(by_station, replacement_set)
        density = self.computeACDensityByTimeOfDay(by_station, replacement_set)

        report = ReplacementReport(
            replacement_set=replacement_set,
            depot=depot,
            semi_fast=semi_fast,
            coverage=coverage,
            followings=followings,
            profiles=profiles,
            beforeAfterMetrics=before_after,
            headwayGaps=headway_gaps,
            acDensityByTod=density,
        )

        if station:
            station = station.upper()
            windows = [PEAK_MORNING, PEAK_EVENING] if peak_only else None
            report.station_arrivals = self.station_sequence(station, None, by_station, time_windows=windows)

        return report

    def graph_summary(self):
        """Print just the followings graph summary (no replacement set)."""
        by_station = self.build_station_sequences(set())
        edges = self.build_followings_graph(by_station)

        top = sorted(edges.items(), key=lambda x: -x[1])[:20]

        degrees = defaultdict(int)
        weighted_degree = defaultdict(int)
        for (link_a, link_b), weight in edges.items():
            degrees[link_a] += 1
            degrees[link_b] += 1
            weighted_degree[link_a] += weight
            weighted_degree[link_b] += weight

        top_nodes = sorted(weighted_degree.items(), key=lambda x: -x[1])[:10]

        parts = [
            f"=== Followings Graph Summary ===",
            f"  Edges: {len(edges)}",
            f"  Total weight: {sum(edges.values())}",
            "",
            "  Top 20 edges by weight:",
            *[f"    {a}-{b}: {w}" for (a, b), w in top],
            "",
            "  Top 10 nodes by weighted degree:",
            *[f"    {node}: degree={degrees[node]}, weight={wd}" for node, wd in top_nodes],
        ]
        return "\n".join(parts)


def format_report(report):
    """Thin CLI formatter for a ReplacementReport."""
    parts = [f"Replacement Set: {{{', '.join(report.replacement_set)}}}"]

    # Depot compatibility
    depot = report.depot
    depot_lines = ["DEPOT COMPATIBILITY"]
    if not depot["links"]:
        depot_lines.append("  No valid profiles found.")
    else:
        for lk in depot["links"]:
            ac_str = " (AC)" if lk["is_ac"] else ""
            depot_lines.append(f"  {lk['name']}: {lk['depot_start']} -> {lk['depot_end']}{ac_str}")
        if depot["self_loops"]:
            depot_lines.append(f"  Self-loop (1 rake): {', '.join(depot['self_loops'])}")
        if depot["pairs"]:
            for src, dst, via_a, via_b in depot["pairs"]:
                depot_lines.append(f"  Pair (2 rakes): {src} <-> {dst}  (swap at {via_a}, {via_b})")
        if depot["unmatched"]:
            depot_lines.append(f"  Unmatched: {', '.join(depot['unmatched'])}")
    parts.append("\n".join(depot_lines))

    # Semi-fast
    sf_lines = ["SEMI-FAST"]
    has_semi_fast = False
    for link, svcs in report.semi_fast.items():
        if svcs:
            sf_lines.append(f"  {link}: {', '.join(svcs)}")
            has_semi_fast = True
    if not has_semi_fast:
        sf_lines.append("  None")
    parts.append("\n".join(sf_lines))

    # Coverage
    cov_lines = ["COVERAGE (services per station per link)"]
    cov = report.coverage
    if cov["stations"]:
        link_hdr = "".join(f"{lk:>5}" for lk in cov["links"])
        cov_lines.append(f"  {'':20}{link_hdr}")
        for stn in cov["stations"]:
            row = cov["matrix"].get(stn, {})
            vals = "".join(f"{row.get(lk, 0):>5}" for lk in cov["links"])
            cov_lines.append(f"  {stn:20}{vals}")
    parts.append("\n".join(cov_lines))

    # Followings
    fol_lines = ["FOLLOWINGS (top 15, replacement set + neighbors)"]
    fol = report.followings
    if fol["matrix"]:
        top = sorted(fol["matrix"].items(), key=lambda x: -x[1])[:15]
        for (a, b), w in top:
            ac_marker = " AC-AC" if (a, b) in fol["ac_ac_pairs"] else ""
            fol_lines.append(f"  {a}-{b}: {w}{ac_marker}")
        fol_lines.append(f"  AC-AC total: {fol['total_ac_ac_followings']}")
    parts.append("\n".join(fol_lines))

    # Profiles
    prof_lines = ["PROFILES"]
    for name, p in report.profiles.items():
        lt = ",".join(l.value for l in p.line_types) if p.line_types else "?"
        dur_h = int(p.duration_minutes // 60)
        dur_m = int(p.duration_minutes % 60)
        prof_lines.append(f"  {p.name}: {p.depot_start}->{p.depot_end}  {p.length_km}km  {dur_h}h{dur_m:02d}m  {p.n_services} svcs  {lt}")
    parts.append("\n".join(prof_lines))

    # Before/After AC Metrics
    if report.beforeAfterMetrics:
        ba = report.beforeAfterMetrics
        b, a, d = ba["before"], ba["after"], ba["delta"]
        ba_lines = ["NETWORK IMPACT SUMMARY"]
        ba_lines.append(f"  Total services analyzed: {ba['total_services']}")
        ba_lines.append(f"  AC services before: {b['ac_services']} ({b['ac_pct']}%)")
        ba_lines.append(f"  AC services after:  {a['ac_services']} ({a['ac_pct']}%)")
        ba_lines.append(f"  Delta: +{d['ac_services']} services (+{d['ac_pct']}%)")

        # Top stations by AC coverage improvement
        if b.get("station_ac_pct") and a.get("station_ac_pct"):
            improvements = []
            for s in a["station_ac_pct"]:
                before_pct = b["station_ac_pct"].get(s, 0)
                after_pct = a["station_ac_pct"].get(s, 0)
                if after_pct > before_pct:
                    improvements.append((s, before_pct, after_pct))
            improvements.sort(key=lambda x: -(x[2] - x[1]))
            if improvements:
                ba_lines.append("  Top AC coverage improvements:")
                for s, bp, ap in improvements[:10]:
                    ba_lines.append(f"    {s:20} {bp:5.1f}% -> {ap:5.1f}%")
        parts.append("\n".join(ba_lines))

    # AC Headway Gaps
    if report.headwayGaps:
        hg_lines = ["AC HEADWAY GAPS (worst first)"]
        for entry in report.headwayGaps[:15]:
            hg_lines.append(
                f"  {entry['station']:20} {entry['direction']:<4}  "
                f"max={entry['maxGap']:.0f}m  mean={entry['meanGap']:.0f}m  "
                f"gaps={entry['count']}  >15m={entry['exceedances']}"
            )
        parts.append("\n".join(hg_lines))

    # Station arrivals
    if report.station_arrivals is not None:
        station_name = report.station_arrivals[0].station if report.station_arrivals else "?"
        arr_lines = [f"ARRIVALS AT {station_name}"]
        if not report.station_arrivals:
            arr_lines.append("  No arrivals found.")
        else:
            for e in report.station_arrivals:
                ac = " AC" if e.is_ac else ""
                arr_lines.append(f"  {fmt_time(e.time)} {e.direction:<4} {e.service_id} {e.rakelink}{ac}")
        parts.append("\n".join(arr_lines))

    return "\n\n".join(parts)


def exportReportXlsx(report):
    """Generate structured XLSX report from a ReplacementReport.

    Returns io.BytesIO buffer ready for download.
    """
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # Sheet 1: Before vs After
        if report.beforeAfterMetrics:
            ba = report.beforeAfterMetrics
            b, a, d = ba["before"], ba["after"], ba["delta"]
            rows = [
                {"Metric": "Total Services", "Before": ba["total_services"], "After": ba["total_services"], "Delta": 0},
                {"Metric": "AC Services", "Before": b["ac_services"], "After": a["ac_services"], "Delta": d["ac_services"]},
                {"Metric": "AC %", "Before": b["ac_pct"], "After": a["ac_pct"], "Delta": d["ac_pct"]},
            ]
            # Add per-station AC%
            for s in sorted(a.get("station_ac_pct", {}).keys(), key=lambda x: DISTANCE_MAP.get(x, 999)):
                bp = b["station_ac_pct"].get(s, 0)
                ap = a["station_ac_pct"].get(s, 0)
                rows.append({"Metric": f"AC% {s}", "Before": bp, "After": ap, "Delta": round(ap - bp, 1)})
            pd.DataFrame(rows).to_excel(writer, sheet_name="Before vs After", index=False)

        # Sheet 2: AC Headway Gaps
        if report.headwayGaps:
            rows = []
            for entry in report.headwayGaps:
                rows.append({
                    "Station": entry["station"],
                    "Direction": entry["direction"],
                    "Max Gap (min)": entry["maxGap"],
                    "Mean Gap (min)": entry["meanGap"],
                    "Gap Count": entry["count"],
                    "Gaps > 15min": entry["exceedances"],
                })
            pd.DataFrame(rows).to_excel(writer, sheet_name="AC Headway Gaps", index=False)

        # Sheet 3: Station Coverage
        cov = report.coverage
        if cov and cov["stations"]:
            rows = []
            for stn in cov["stations"]:
                row = {"Station": stn, "Distance (km)": DISTANCE_MAP.get(stn, 0)}
                for lk in cov["links"]:
                    row[lk] = cov["matrix"].get(stn, {}).get(lk, 0)
                rows.append(row)
            pd.DataFrame(rows).to_excel(writer, sheet_name="Station Coverage", index=False)

        # Sheet 4: AC Density by Hour
        if report.acDensityByTod:
            density = report.acDensityByTod
            rows = []
            for s in density["stations"]:
                row_before = {"Station": s, "State": "Before"}
                row_after = {"Station": s, "State": "After"}
                for bl in density["buckets"]:
                    row_before[bl] = density["before"][s].get(bl, 0)
                    row_after[bl] = density["after"][s].get(bl, 0)
                rows.append(row_before)
                rows.append(row_after)
            pd.DataFrame(rows).to_excel(writer, sheet_name="AC Density by Hour", index=False)

        # Sheet 5: Link Followings
        fol = report.followings
        if fol and fol["matrix"]:
            ac_pair_set = set(tuple(p) for p in fol.get("ac_ac_pairs", []))
            rows = []
            for (a, b), w in sorted(fol["matrix"].items(), key=lambda x: -x[1]):
                rows.append({
                    "Link A": a,
                    "Link B": b,
                    "Weight": w,
                    "AC-AC": "Yes" if (a, b) in ac_pair_set else "No",
                })
            pd.DataFrame(rows).to_excel(writer, sheet_name="Link Followings", index=False)

        # Sheet 6: Link Profiles
        if report.profiles:
            rows = []
            for name, p in report.profiles.items():
                lt = ",".join(l.value for l in p.line_types) if p.line_types else "?"
                rows.append({
                    "Link": p.name,
                    "Depot Start": p.depot_start,
                    "Depot End": p.depot_end,
                    "Distance (km)": p.length_km,
                    "Duration (min)": p.duration_minutes,
                    "Services": p.n_services,
                    "Line Types": lt,
                    "Is AC": p.is_ac,
                })
            pd.DataFrame(rows).to_excel(writer, sheet_name="Link Profiles", index=False)

        # Sheet 7: Arrival Sequence (if specified)
        if report.station_arrivals:
            rows = []
            for e in report.station_arrivals:
                rows.append({
                    "Time": fmt_time(e.time),
                    "Direction": e.direction,
                    "Service": e.service_id,
                    "Rakelink": e.rakelink,
                    "AC": "Yes" if e.is_ac else "No",
                    "Originally AC": "Yes" if e.originally_ac else "No",
                })
            pd.DataFrame(rows).to_excel(writer, sheet_name="Arrival Sequence", index=False)

    buf.seek(0)
    return buf
