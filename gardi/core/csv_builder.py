"""Centralized CSV export builder for WTT data."""

import json
import logging
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd

from gardi.core.models import DISTANCE_MAP, Line

logger = logging.getLogger(__name__)

# Map pattern-file station names to DISTANCE_MAP station names
PATTERN_STATION_MAP = {
    "Mumbai Central": "M'BAI CENTRAL(L)",
    "Mahim Junction": "MAHIM JN.",
    "Nalla Sopara": "NALLASOPARA",
    "Santacruz": "SANTA CRUZ",
    "Kandivli": "KANDIVALI",
}


# Ordered station list derived from DISTANCE_MAP
STATIONS_ORDERED = sorted(DISTANCE_MAP.keys(), key=lambda s: DISTANCE_MAP[s])

# Adjacent station pairs: (station_a, station_b, distance_km between them)
ADJACENT_PAIRS = []
for i in range(len(STATIONS_ORDERED) - 1):
    a, b = STATIONS_ORDERED[i], STATIONS_ORDERED[i + 1]
    ADJACENT_PAIRS.append((a, b, round(DISTANCE_MAP[b] - DISTANCE_MAP[a], 1)))

_ADJACENT_SET = set()
for a, b, _ in ADJACENT_PAIRS:
    _ADJACENT_SET.add((a, b))
    _ADJACENT_SET.add((b, a))


def _fmt(t):
    """Format minutes since midnight to HH:MM."""
    if t is None:
        return "--:--"
    t = int(round(t))
    return f"{t // 60:02.0f}:{t % 60:02.0f}"


class TraversalAnalyzer:
    """Computes inter-station run times from parsed WTT services."""

    def analyze(self, wtt):
        """Return (DataFrame, metadata_dict) of traversal times."""
        # Collect raw run times keyed by (station_a, station_b, direction)
        samples = defaultdict(list)
        total_services = 0

        services = wtt.suburbanServices or (wtt.upServices + wtt.downServices)

        for svc in services:
            if not svc.events or len(svc.events) < 2:
                continue
            total_services += 1
            direction = svc.direction.name if svc.direction else "UNKNOWN"

            if not svc.legs:
                svc.build_legs()
            for leg in svc.legs:
                if (leg.from_station, leg.to_station) not in _ADJACENT_SET:
                    continue
                if leg.run_minutes <= 0 or leg.run_minutes > 30:
                    continue  # skip implausible values
                samples[(leg.from_station, leg.to_station, direction)].append(leg.run_minutes)

        # Build rows
        rows = []
        for (st_a, st_b, direction), times in samples.items():
            dist = abs(DISTANCE_MAP.get(st_a, 0) - DISTANCE_MAP.get(st_b, 0))
            rows.append({
                "station_a": st_a,
                "station_b": st_b,
                "distance_km": round(dist, 1),
                "direction": direction,
                "median_time": round(statistics.median(times), 1),
                "sample_count": len(times),
                "min_time": min(times),
                "max_time": max(times),
                "std_dev": round(statistics.stdev(times), 2) if len(times) > 1 else 0.0,
            })

        # Sort by direction then station order
        def sort_key(row):
            dir_ord = 0 if row["direction"] == "UP" else 1
            a_dist = DISTANCE_MAP.get(row["station_a"], 999)
            return (dir_ord, a_dist)

        rows.sort(key=sort_key)
        df = pd.DataFrame(rows)
        for col in ("sample_count", "min_time", "max_time"):
            if col in df.columns:
                df[col] = df[col].astype(int)

        low_sample_pairs = sum(1 for r in rows if r["sample_count"] < 10)
        metadata = {
            "total_services_sampled": total_services,
            "pair_count": len(rows),
            "pairs_with_low_samples": low_sample_pairs,
        }

        return df, metadata


def timingSplit(wtt, start="VIRAR", end="CHURCHGATE"):
    """Per-service timing for a corridor.

    Returns (DataFrame, metadata_dict). Each row is one service that covers
    the full start->end corridor, with start/end times and duration.
    """
    start, end = start.upper(), end.upper()
    if start not in DISTANCE_MAP:
        raise ValueError(f"Unknown station: {start}")
    if end not in DISTANCE_MAP:
        raise ValueError(f"Unknown station: {end}")

    services = wtt.suburbanServices or (wtt.upServices + wtt.downServices)
    rows = []

    for svc in services:
        if not svc.events or len(svc.events) < 2:
            continue

        # Check if service visits both start and end stations
        stations_visited = [evt.atStation for evt in svc.events]
        if start not in stations_visited or end not in stations_visited:
            continue

        # Determine corridor direction based on event order
        first_start = stations_visited.index(start)
        first_end = stations_visited.index(end)
        if first_start < first_end:
            corridor_from, corridor_to = start, end
        else:
            corridor_from, corridor_to = end, start

        # Departure from corridor start: use the LAST event at that station (departure)
        depart_time = None
        for evt in svc.events:
            if evt.atStation == corridor_from and evt.atTime is not None:
                depart_time = evt.atTime

        # Arrival at corridor end: use the FIRST event at that station (arrival)
        # Terminal guard: if end station has 2+ events (arrival + turnaround), take the first
        arrive_time = None
        for evt in svc.events:
            if evt.atStation == corridor_to and evt.atTime is not None:
                arrive_time = evt.atTime
                break  # first event = arrival

        if depart_time is None or arrive_time is None:
            continue

        # Duration via simple subtraction (with midnight wrap)
        duration = arrive_time - depart_time
        if duration < 0:
            duration += 1440

        sid = "/".join(str(s) for s in svc.serviceId) if svc.serviceId else "?"
        direction = svc.direction.name if svc.direction else "?"
        line_label = "Fast" if svc.line == Line.THROUGH else "Slow" if svc.line == Line.LOCAL else "Semi-Fast" if svc.line == Line.SEMI_FAST else "?"
        ac_label = "AC" if svc.needsACRake else "NAC"

        rows.append({
            "serviceId": sid,
            "direction": direction,
            "lineType": line_label,
            "ac": ac_label,
            "startTime": _fmt(depart_time),
            "endTime": _fmt(arrive_time),
            "durationMins": round(duration),
        })

    # Sort by line type (Fast, Slow, Semi-Fast), then startTime
    line_order = {"Fast": 0, "Slow": 1, "Semi-Fast": 2, "?": 3}
    rows.sort(key=lambda r: (line_order.get(r["lineType"], 3), r["startTime"]))
    df = pd.DataFrame(rows)

    metadata = {
        "corridor": f"{start} -> {end}",
        "services_matched": len(rows),
    }
    return df, metadata


def allServices(wtt):
    """List all services with line type and switching station info.

    Returns (DataFrame, metadata_dict).
    """
    services = wtt.suburbanServices or (wtt.upServices + wtt.downServices)
    rows = []

    for svc in services:
        if not svc.events or len(svc.events) < 2:
            continue

        sid = "/".join(str(s) for s in svc.serviceId) if svc.serviceId else "?"
        start_time = svc.events[0].atTime
        source = svc.initStation.name if svc.initStation else "?"
        destination = svc.finalStation.name if svc.finalStation else "?"
        direction = svc.direction.name if svc.direction else "?"
        line_label = "Fast" if svc.line == Line.THROUGH else "Slow" if svc.line == Line.LOCAL else "Semi-Fast" if svc.line == Line.SEMI_FAST else "?"

        # Find switching stations for semi-fast services
        switch_station = ""
        if line_label == "Semi-Fast" and svc.lineSwitches:
            switches = []
            for i in range(1, len(svc.lineSwitches)):
                if svc.lineSwitches[i][1] != svc.lineSwitches[i - 1][1]:
                    switches.append(svc.lineSwitches[i][0])
            switch_station = "/".join(switches)

        rows.append({
            "serviceId": sid,
            "startTime": _fmt(start_time),
            "source": source,
            "destination": destination,
            "direction": direction,
            "line": line_label,
            "switchStation": switch_station,
        })

    line_order = {"Fast": 0, "Slow": 1, "Semi-Fast": 2, "?": 3}
    rows.sort(key=lambda r: (line_order.get(r["line"], 3), r["startTime"]))
    df = pd.DataFrame(rows)

    metadata = {
        "service_count": len(rows),
    }
    return df, metadata


def turnaround(wtt, station):
    """Turnaround time distribution at a terminal station.

    Returns (DataFrame, metadata_dict). Each row is one service that
    arrives at the given station and has a terminal departure event.
    """
    station = station.upper()
    if station not in DISTANCE_MAP:
        raise ValueError(f"Unknown station: {station}")

    services = wtt.suburbanServices or (wtt.upServices + wtt.downServices)
    rows = []

    for svc in services:
        if not svc.events or len(svc.events) < 2:
            continue
        last = svc.events[-1]
        second_last = svc.events[-2]
        if (last.isTerminalDeparture
                and second_last.atStation == station
                and second_last.atTime is not None
                and last.atTime is not None):
            turn_mins = last.atTime - second_last.atTime
            if turn_mins < 0:
                turn_mins += 1440
            rows.append({
                "arrivalTime": _fmt(second_last.atTime),
                "turnaroundMins": round(turn_mins),
            })

    rows.sort(key=lambda r: r["arrivalTime"])
    df = pd.DataFrame(rows)

    median_turn = round(statistics.median(r["turnaroundMins"] for r in rows), 1) if rows else 0
    metadata = {
        "station": station,
        "total_turnarounds": len(rows),
        "median_turnaround_mins": median_turn,
    }
    return df, metadata


def _resolve_station(name):
    """Convert a pattern station name to DISTANCE_MAP key."""
    return PATTERN_STATION_MAP.get(name, name.upper())


def _load_patterns():
    """Load and resolve patterns.json into usable structures.

    Returns dict: pattern_name -> {
        'type': int,
        'segment_keys': [str, ...],
        'segments': [(from_station, to_station), ...],
        'stations': [str, ...],  # ordered station chain
    }
    """
    patterns_path = Path(__file__).resolve().parent.parent.parent / "patterns.json"
    with open(patterns_path) as f:
        raw = json.load(f)

    # Build segment lookup: key -> (from_station, to_station)
    seg_lookup = {}
    for key, desc in raw.get("fast_segments", {}).items():
        parts = desc.split("-", 1)
        seg_lookup[key] = (_resolve_station(parts[0]), _resolve_station(parts[1]))
    for key, desc in raw.get("slow_segments", {}).items():
        parts = desc.split("-", 1)
        seg_lookup[key] = (_resolve_station(parts[0]), _resolve_station(parts[1]))

    # Build resolved patterns
    patterns = {}
    for name, info in raw.get("patterns", {}).items():
        seg_keys = info["segments"]
        segments = [seg_lookup[k] for k in seg_keys]
        # Build ordered station chain from segments
        stations = [segments[0][0]]
        for seg in segments:
            stations.append(seg[1])
        patterns[name] = {
            "type": info["type"],
            "segment_keys": seg_keys,
            "segments": segments,
            "stations": stations,
        }

    return patterns, raw


class CsvBuilder:
    """Centralized CSV export with headers for CLI and UI use."""

    def __init__(self):
        self._traversal = TraversalAnalyzer()
        self._patterns_cache = None

    def traversalTimes(self, wtt):
        """Return CSV string with header for traversal time analysis."""
        df, meta = self._traversal.analyze(wtt)
        header = (
            f"# Traversal Time Analysis\n"
            f"# Services sampled: {meta['total_services_sampled']}\n"
            f"# Station pairs: {meta['pair_count']}\n"
            f"# Pairs with <10 samples: {meta['pairs_with_low_samples']}\n"
        )
        return header + df.to_csv(index=False)

    def timingSplit(self, wtt, start="VIRAR", end="CHURCHGATE"):
        """Return CSV string with header for corridor timing split."""
        df, meta = timingSplit(wtt, start, end)
        header = (
            f"# Timing Split: {meta['corridor']}\n"
            f"# Services matched: {meta['services_matched']}\n"
        )
        return header + df.to_csv(index=False)

    def allServices(self, wtt):
        """Return CSV string with header for all services listing."""
        df, meta = allServices(wtt)
        header = (
            f"# All Services\n"
            f"# Services: {meta['service_count']}\n"
        )
        return header + df.to_csv(index=False)

    def turnaround(self, wtt, station):
        """Return CSV string with header for turnaround time analysis."""
        df, meta = turnaround(wtt, station)
        header = (
            f"# Turnaround Times: {meta['station']}\n"
            f"# Total turnarounds: {meta['total_turnarounds']}\n"
            f"# Median turnaround: {meta['median_turnaround_mins']} mins\n"
        )
        return header + df.to_csv(index=False)

    def _get_patterns(self):
        """Lazy-load and cache patterns."""
        if self._patterns_cache is None:
            self._patterns_cache, self._patterns_raw = _load_patterns()
        return self._patterns_cache

    def patternSegments(self, wtt):
        """Match rendered services to route patterns and compute per-segment durations.

        Returns CSV string. Each row is a (service, pattern) match with per-segment
        duration columns.
        """
        patterns = self._get_patterns()
        services = wtt.suburbanServices or (wtt.upServices + wtt.downServices)

        # Collect all unique segment keys across all patterns for column ordering
        all_seg_keys = []
        seen_keys = set()
        for pinfo in patterns.values():
            for k in pinfo["segment_keys"]:
                if k not in seen_keys:
                    all_seg_keys.append(k)
                    seen_keys.add(k)

        # Build segment labels from raw data
        raw = self._patterns_raw
        seg_labels = {}
        for k, desc in raw.get("fast_segments", {}).items():
            seg_labels[k] = desc
        for k, desc in raw.get("slow_segments", {}).items():
            seg_labels[k] = desc

        rows = []
        for svc in services:
            if not svc.render:
                continue
            if not svc.events or len(svc.events) < 2:
                continue
            if not svc.legs:
                svc.build_legs()

            # Build station sequence from legs
            svc_stations = [svc.legs[0].from_station]
            for leg in svc.legs:
                svc_stations.append(leg.to_station)

            for pat_name, pinfo in patterns.items():
                # Filter by line type: fast patterns (type>0) for fast services,
                # slow patterns (type<0) for slow services, semi-fast matches both
                pat_type = pinfo["type"]
                if svc.line == Line.THROUGH and pat_type < 0:
                    continue
                if svc.line == Line.LOCAL and pat_type > 0:
                    continue

                pat_stations = pinfo["stations"]

                # Check if service covers all pattern stations in order
                si = 0
                for ps in pat_stations:
                    found = False
                    while si < len(svc_stations):
                        if svc_stations[si] == ps:
                            found = True
                            si += 1
                            break
                        si += 1
                    if not found:
                        break
                else:
                    # Match found - compute per-segment durations
                    seg_durations = {}
                    leg_idx = 0
                    for seg_key, (seg_from, seg_to) in zip(pinfo["segment_keys"], pinfo["segments"]):
                        # Find legs covering this segment
                        total = 0.0
                        # Advance to the leg starting at seg_from
                        while leg_idx < len(svc.legs) and svc.legs[leg_idx].from_station != seg_from:
                            leg_idx += 1
                        # Sum legs until we reach seg_to
                        start_idx = leg_idx
                        while leg_idx < len(svc.legs):
                            total += svc.legs[leg_idx].run_minutes
                            if svc.legs[leg_idx].to_station == seg_to:
                                leg_idx += 1
                                break
                            leg_idx += 1
                        seg_durations[seg_key] = round(total, 1)

                    total_mins = sum(seg_durations.values())
                    sid = "/".join(str(s) for s in svc.serviceId) if svc.serviceId else "?"
                    direction = svc.direction.name if svc.direction else "?"
                    line_label = "Fast" if svc.line == Line.THROUGH else "Slow" if svc.line == Line.LOCAL else "Semi-Fast" if svc.line == Line.SEMI_FAST else "?"
                    ac_label = "AC" if svc.needsACRake else "NAC"
                    start_time = _fmt(svc.events[0].atTime) if svc.events[0].atTime is not None else "?"

                    row = {
                        "serviceId": sid,
                        "direction": direction,
                        "lineType": line_label,
                        "acType": ac_label,
                        "patternName": pat_name,
                        "startTime": start_time,
                    }
                    for k in pinfo["segment_keys"]:
                        row[k] = seg_durations.get(k, "")
                    row["totalMins"] = round(total_mins, 1)
                    rows.append(row)

        if not rows:
            return "# No services matched any pattern\n"

        # Build column order: fixed cols + all segment keys that appear in results + totalMins
        used_seg_keys = []
        for k in all_seg_keys:
            if any(k in r for r in rows):
                used_seg_keys.append(k)

        columns = ["serviceId", "direction", "lineType", "acType", "patternName", "startTime"] + used_seg_keys + ["totalMins"]
        df = pd.DataFrame(rows, columns=columns)

        # Rename segment columns to their labels
        rename = {k: seg_labels.get(k, k) for k in used_seg_keys}
        df = df.rename(columns=rename)

        # Build summary: group matched patterns by service
        svc_patterns = defaultdict(list)
        for r in rows:
            svc_patterns[r["serviceId"]].append(r["patternName"])

        unique_services = len(svc_patterns)
        header = (
            f"# Pattern Segment Durations\n"
            f"# Unique services: {unique_services}\n"
            f"# Total matches (service x pattern): {len(rows)}\n"
        )
        summary_lines = []
        for sid, pats in svc_patterns.items():
            summary_lines.append(f"# Service {sid}: {len(pats)} patterns,\"{', '.join(pats)}\"")
        summary = "\n".join(summary_lines) + "\n"

        return header + summary + df.to_csv(index=False)
