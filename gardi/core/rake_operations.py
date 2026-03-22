#!/usr/bin/env python3


class RakeOperations:
    def convert_to_ac(self, wtt, link_names):
        """
        Convert specified rake links to AC.
        Updates both Rake and Service objects.

        Args:
            wtt: TimeTable object
            link_names: List of rake link names (e.g., ['A', 'B'])

        Returns:
            dict with conversion summary
        """
        if not link_names:
            return {"converted": 0, "links": []}

        converted = []

        for rc in wtt.rakecycles:
            if rc.linkName in link_names:
                # Skip if already AC
                if rc.rake and rc.rake.isAC:
                    continue

                # Convert the rake
                if rc.rake:
                    rc.rake.isAC = True

                # Convert all services in this rake cycle
                for svc in rc.servicePath:
                    svc.needsACRake = True

                converted.append(rc.linkName)

        return {"converted": len(converted), "links": converted}

    def detect_gaps(self, wtt, size_minutes, stations, time_range, events_by_station_map):
        """
        Finds service gaps > threshold at stations.

        Args:
            wtt: TimeTable object
            size_minutes: Gap threshold in minutes
            stations: List of station names
            time_range: Tuple (t_lower, t_upper) in minutes
            events_by_station_map: Dict mapping station names to event lists
        """
        print(f"# Gaps > {size_minutes} minutes:")
        t_lower, t_upper = time_range

        for stn in stations:
            events = events_by_station_map.get(stn, [])
            if not events:
                print(f"{stn}: 0")
                continue

            # collect only times inside the given range
            times = [e.atTime for e in events if t_lower <= e.atTime <= t_upper]

            if not times:
                print(f"{stn}: 0")
                continue

            times.sort()

            gapCount = 0
            for i in range(1, len(times)):
                if (times[i] - times[i - 1]) > size_minutes:
                    gapCount += 1

            print(f"{stn}: {gapCount}")
