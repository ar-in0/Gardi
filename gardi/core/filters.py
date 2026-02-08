#!/usr/bin/env python3

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


class FilterType(Enum):
    RAKELINK = "rakelink"
    SERVICE = "service"
    STATION = "station"


@dataclass
class FilterQuery:
    type: Optional[FilterType] = None

    # Make fields mode-specific (no properties needed)
    startStation: Optional[str] = None
    endStation: Optional[str] = None
    passingThrough: List[str] = field(default_factory=list)
    inTimePeriod: Optional[Tuple[int, int]] = (165, 1605)

    ac: Optional[bool] = None
    inDirection: Optional[List[str]] = None
    selectedLinks: List[str] = field(default_factory=list)
    selectedServices: List[str] = field(default_factory=list)


class FilterEngine:
    def reset_all_flags(self, wtt):
        for rc in wtt.rakecycles:
            rc.render = True

        for svc in wtt.suburbanServices:
            if not svc.events:
                svc.render = False
                continue
            svc.render = True
            for ev in svc.events:
                ev.render = True

    def apply_filters(self, wtt, qq):
        if qq.type == FilterType.SERVICE:
            self.apply_service_filters(wtt, qq)
        elif qq.type == FilterType.STATION:
            self.apply_station_filters(wtt, qq)
        else:
            self.apply_link_filters(wtt, qq)

    def apply_link_filters(self, wtt, qq):
        """Filter rake cycles based on selected start and end stations."""
        self._apply_terminal_station_filters(wtt, qq.startStation, qq.endStation)
        self._apply_passing_through_filter(wtt, qq)
        self._apply_ac_filter(wtt, qq)

        visible_count = len([r for r in wtt.rakecycles if r.render])
        print(f"Visible rake cycles after filter: {visible_count}")

    def _apply_terminal_station_filters(self, wtt, start, end):
        print(f"Applying filters: start={start}, end={end}")

        for rc in wtt.rakecycles:
            rc.render = True  # reset all first
            if not rc.servicePath:
                rc.render = False
                continue

            first = rc.servicePath[0].events[0].atStation
            last = rc.servicePath[-1].events[-1].atStation

            if start and start.upper() != first:
                rc.render = rc.render and False
            if end and end.upper() != last:
                rc.render = rc.render and False

    def _apply_passing_through_filter(self, wtt, qq):
        """Make rakecycles visible that have events at every station in passingThru within the specified timeperiod"""
        selected = qq.passingThrough
        print(qq.passingThrough)
        if not selected:
            return

        selected = [s.upper() for s in selected]
        t_start, t_end = qq.inTimePeriod if qq.inTimePeriod else (None, None)

        for rc in wtt.rakecycles:
            rc.render = rc.render and True
            if not rc.servicePath:
                rc.render = rc.render and False
                continue

            # flatten all events in this rakecycle
            el = []
            for s in rc.servicePath:
                el.extend(s.events)

            # filter by time
            if qq.inTimePeriod:
                filtered = []
                for e in el:
                    if not e.atTime:
                        continue

                    minutes = e.atTime

                    if t_start <= minutes <= t_end:
                        filtered.append(e)
                el = filtered  # keep only events inside window

            # station membership check
            seen = set()
            for e in el:
                if not e.atStation:
                    continue
                stName = str(e.atStation).strip().upper()
                if stName in selected:
                    seen.add(stName)
                if len(seen) == len(selected):
                    break

            if len(seen) < len(selected):
                rc.render = False

    def _apply_ac_filter(self, wtt, qq):
        """Render only AC / Non-AC / All rake cycles as per filter."""
        mode = qq.ac
        if mode is None or mode == "all":
            return  # no filtering

        for rc in wtt.rakecycles:
            if not rc.rake:
                rc.render = False
                continue

            if mode == "ac" and not rc.rake.isAC:
                rc.render = False
            elif mode == "nonac" and rc.rake.isAC:
                rc.render = False

    def apply_service_filters(self, wtt, qq):
        """
        Filters individual services based on the Service tab query constraints.
        Sets the 'render' flag on each Service object.
        Also updates the parent RakeCycle 'render' flag.
        """
        for svc in wtt.suburbanServices:
            svc.render = True

            if not svc.events:  # invalid
                svc.render = False
                continue
            # Also reset event render flags
            for ev in svc.events:
                ev.render = True

            # check if the service satisfies the
            # start and end station constraint
            svc.checkDirectionConstraint(qq)
            svc.checkACConstraint(qq)
            svc.checkStartStationConstraint(qq)
            svc.checkEndStationConstraint(qq)
            svc.checkPassingThroughConstraint(qq)
            print(f"constraint checks done for {svc}")

        for rc in wtt.rakecycles:
            rc.render = False
            if rc.servicePath:
                if any(svc.render for svc in rc.servicePath):
                    rc.render = True

        visible_services = len(
            [s for s in wtt.suburbanServices if s.render]
        )
        visible_cycles = len([r for r in wtt.rakecycles if r.render])

    def apply_station_filters(self, wtt, qq):
        t_lower, t_upper = qq.inTimePeriod
        for rc in wtt.rakecycles:
            rc.render = True

        for svc in wtt.suburbanServices:
            svc.render = True

            # FIX: Check if events exist before accessing
            if not svc.events:
                svc.render = False
                continue

            for ev in svc.events:
                ev.render = True

                # FIX: Check if atTime exists
                if ev.atTime is None:
                    ev.render = False
                    continue

                t = ev.atTime
                if not (t_lower <= t <= t_upper):
                    ev.render = False

            svc.checkACConstraint(qq)
