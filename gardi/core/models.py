## How to represent a Rake-Cycle after parsing the timetable?
# Option1: Maintain a unique list of station objects per rake cycle.
# Store arrival times in each station object. Too much repetition.
#
# Option2: A single set of station objects.
# Currently using option2
# We want to plot the entire journey in a single day, and in particular,
# during the peak hour
import pandas as pd
import re
from collections import defaultdict
import logging
from datetime import datetime
import time

logging.basicConfig(
    level=logging.DEBUG,
    format='[%(levelname)s]: %(message)s'
)
logger = logging.getLogger(__name__)

# to check column colour, need to create an authentication
# with google sheets. Downloading the file strips colour information.

# @oct24
# services have start end stations
# rake cycles have start end depot

SERVICE_ID_LEN = 5

from enum import Enum

class RakeLinkStatus(Enum):
    VALID = 'valid'
    INVALID = 'invalid'

# initially we onl handle regular suburban trains
# excluding dahanu road
# services
class ServiceType(Enum):
    REGULAR = 'regular'
    STABLING = 'stabling'
    MULTI_SERVICE = 'multi-service'

class ServiceZone(Enum):
    SUBURBAN = 'suburban'
    CENTRAL = 'central'

class Direction(Enum):
    UP = 'up'
    DOWN = 'down'

class Day(Enum):
    MONDAY = 'monday'
    TUESDAY = 'tuesday'
    WEDNESDAY = 'wednesday'
    THURSDAY = 'thursday'
    FRIDAY = 'friday'
    SATURDAY = 'saturday'
    SUNDAY = 'sunday'

class Line(Enum):
    THROUGH = 'through/fast'
    LOCAL = 'local/slow'
    UNKNOWN = 'unknown'

class EventType(Enum):
    ARRIVAL = 'ARRIVAL',
    DEPARTURE = 'DEPARTURE'

# From https://bhaaratham.com/list-of-stations-mumbai-local-train/
DISTANCE_MAP = {
    "CHURCHGATE": 0, "MARINE LINES": 2, "CHARNI ROAD": 3, "GRANT ROAD": 4,
    "M'BAI CENTRAL(L)": 5, "MAHALAKSHMI": 6, "LOWER PAREL": 8, "PRABHADEVI": 9,
    "DADAR": 11, "MATUNGA ROAD": 11.5, "MAHIM JN.": 12, "BANDRA": 15,
    "KHAR ROAD": 17, "SANTA CRUZ": 18, "VILE PARLE": 20, "ANDHERI": 22,
    "JOGESHWARI": 24, "RAM MANDIR": 25.5, "GOREGAON": 27, "MALAD": 30, "KANDIVALI": 32,
    "BORIVALI": 34, "DAHISAR": 37, "MIRA ROAD": 40, "BHAYANDAR": 44,
    "NAIGAON": 48, "VASAI ROAD": 52, "NALLASOPARA": 56, "VIRAR": 60
}


def normalize_station_name(name: str) -> str:
    """Normalize known station name inconsistencies in WTT data."""
    name = str(name).strip()
    if name == "M'BAI CENTRAL (L)":
        name = "M'BAI CENTRAL(L)"
    if name.upper() == "KANDIVLI":
        name = "KANDIVALI"
    return name


class TimeTable:
    def __init__(self):
        # ground truth
        self.xlsxSheets = []

        self.rakes = [Rake(i) for i in range(1,100)] # each rake has an id 1-100
        self.stations = {} # stationName: <Station>

        self.upServices = []
        self.downServices = []
        self.suburbanServices = None

        self.stationEvents = {} # station: StationEvent
        self.serviceChains = [] # created by following the serviceids across sheets

        self.rakecycles = [] # needs timing info
        self.allCyclesWtt = [] # from wtt linked follow
        self.conflictingLinks = []

    def storeOriginalACStates(self):
        """Store original AC states for reset capability"""
        self.originalACStates = {}
        for rc in self.rakecycles:
            if rc.rake:
                self.originalACStates[rc.linkName] = rc.rake.isAC
            # Also store service AC requirements
            for svc in rc.servicePath if rc.servicePath else []:
                self.originalACStates[f"svc_{svc.serviceId[0]}"] = svc.needsACRake

    def resetACStates(self):
        """Reset all AC states to original"""
        if not hasattr(self, 'originalACStates'):
            return

        for rc in self.rakecycles:
            if rc.rake and rc.linkName in self.originalACStates:
                rc.rake.isAC = self.originalACStates[rc.linkName]

            # Reset service AC requirements
            if rc.servicePath:
                for svc in rc.servicePath:
                    key = f"svc_{svc.serviceId[0]}"
                    if key in self.originalACStates:
                        svc.needsACRake = self.originalACStates[key]


    # We have a digraph, with nodes v repreented by
    # Services, and edge (u,v) rep by `u.linkedTo = v`.
    # Rake-Links are CCs of the graph.
    # Our task is to identify the CCs given a set of Nodes
    # and Edges ie. G = (V, E)
    # Invariants for valid WTT:
    # - No cycles in CCs
    def makeRakeCyclePathsSV(self, services):
        '''
        Build rake-cycle paths by recursively following directed `linkedTo` chains.
        Each service node stores both `prev` and `next` links.
        '''
        idMap = {sid: s for s in services for sid in s.serviceId}
        adj = defaultdict(lambda: {'prev': None, 'next': None})

        # build directed links
        for sv in idMap.values():
            sid = sv.serviceId[0]
            if not sv.linkedTo:
                continue
            try:
                nextId = int(str(sv.linkedTo).strip())
            except ValueError:
                nextId = str(sv.linkedTo).strip()

            if nextId not in idMap:
                continue

            adj[sid]['next'] = nextId
            adj[nextId]['prev'] = sid

        visited = set()

        def followChain(sid, chain):
            if sid in visited or sid not in idMap:
                return
            visited.add(sid)
            chain.append(idMap[sid])
            nxt = adj[sid]['next']
            if nxt:
                followChain(nxt, chain)

        for sid in idMap:
            if sid in visited:
                continue
            if adj[sid]['prev'] is not None:
                continue  # not a starting node
            if adj[sid]['next'] is None:
                continue  # isolated or terminal only

            chain = []
            followChain(sid, chain)
            if chain:
                self.allCyclesWtt.append(chain)

    # rc: rake cycle
    def fixPath(self, rc):
        linkName = rc.linkName
        logger.info(f"Fixing serviceID path for rakecycle {linkName}")
        sid = rc.serviceIds[0]

        if rc.undefinedIds:
            logger.debug(f"Services {rc.undefinedIds} not defined in the WTT. Discarding the link.")
            rc.status = RakeLinkStatus.INVALID
            return []

        allServices = {str(s.serviceId[0]): s for s in self.suburbanServices}
        s = allServices.get(str(sid))
        if not s:
            raise ValueError(f"Service {sid} not found for link {linkName}")

        if any(str(sid) == str(sv.linkedTo) for sv in allServices.values()):
            logger.debug(f"Service {sid} appears as a linkedTo of another service in WTT. Possible mislink in rakecycle {linkName}.")
            logger.info("Treat summary as source of truth. Reconstruct path using the serviceIds in the summary")
            path = []
            for id in rc.serviceIds:
                svc = allServices.get(str(id))
                if not svc:
                    raise ValueError(f"Service {id} not found for link {linkName}")
                path.append(svc)
            return path

    # creates stationEvents
    def generateRakeCycles(self, parser):
        self.suburbanServices.sort(
            key=lambda sv: (
                isinstance(sv.serviceId[0], int),
                sv.serviceId[0]
            )
        )

        self.makeRakeCyclePathsSV(self.suburbanServices)

        for path in self.allCyclesWtt:
            sidpath = [s.serviceId[0] for s in path]

        invalid = []
        for rc in self.rakecycles:
            for path in self.allCyclesWtt:
                if str(rc.serviceIds[0]) == str(path[0].serviceId[0]):
                    rc.servicePath = path
            if not rc.servicePath:
                logger.debug(f"Link {rc.linkName}: Summ starts with: {str(rc.serviceIds[0])}, wtt starts with: {str(path[0].serviceId[0])}")
                logger.warning(f"Unable to match rakelink {rc.linkName} to a wtt-derived service-path. Fixing...")
                fixedPath = self.fixPath(rc)
                if rc.status == RakeLinkStatus.INVALID:
                    invalid.append(rc)
                rc.servicePath = fixedPath

        for rc in invalid:
            self.rakecycles.remove(rc)

        logger.debug(f"# Rakecycles after fixing: {len(self.rakecycles)}")

        self.validateRakeCycles()

        logger.debug(f"After fixup and validation, we have {len(self.rakecycles)} consistent cycles.")

        for rc in self.rakecycles:
            sPath = [svc.serviceId[0] for svc in rc.servicePath]
            print(f"{rc.linkName}: {sPath}")
            rcRawServiceCols = []
            if not rc.servicePath:
                pass
            for svc in rc.servicePath:
                rcRawServiceCols.append(svc.rawServiceCol)
                svc.generateStationEvents(parser)
                if not svc.events:
                    raise ValueError(f"Service {svc.serviceId} has no events")
                svc.initStation = self.stations[svc.events[0].atStation]
                svc.finalStation = self.stations[svc.events[-1].atStation]

                # calculate service distance
                svc.computeLengthKm()
                rc.lengthKm += svc.lengthKm
                svc.computeDurationMinutes()
                rc.durationMinutes += svc.durationMinutes
            print("\n")
            print(f"**Count = {len(sPath)}**")
            df = pd.DataFrame(rcRawServiceCols).T
            print(df.to_string())
            print("\n\n\n")
        # assign rakes to rakecycles
        self.assignRakes()

    def assignRakes(self):
        for i, rc in enumerate(self.rakecycles):
            rake = Rake(i)
            for svc in rc.servicePath:
                if svc.needsACRake:
                    rake.isAC = True
                    break
                if svc.rakeSizeReq:
                    rake.rakeSize = svc.rakeSizeReq
                    break
            rc.rake = rake


    def printStatistics(self):
        pass

    def validateRakeCycles(self):
        cycles = self.rakecycles
        logger.debug("Removing inexact rakecycle matches.")
        for rc in cycles:
            summaryPath = rc.serviceIds
            wttPath = [svc.serviceId[0] for svc in rc.servicePath]

            # check reduced path1
            summaryPathRed1 = summaryPath[:-2]

            if wttPath != summaryPath:
                if summaryPath[:-1] == wttPath:
                    if "ETY" in str(summaryPath[-1]):
                        continue
                else:
                    if summaryPath[:-2] == wttPath:
                        if "ETY" in str(summaryPathRed1[-1]) and "ETY" in str(summaryPath[-1]):
                            continue
                self.conflictingLinks.append((rc, wttPath))

        for rc in self.conflictingLinks:
            self.rakecycles.remove(rc[0])

class Rake:
    '''Physical rake specifications.'''
    def __init__(self, rakeId):
        self.rakeId = rakeId
        self.isAC = False
        self.rakeSize = 12 # How many cars in this rake?
        self.velocity = 1 # can make it a linear model
        self.assignedToLink = None  # which rake-cycle is it used for?

    def __repr__(self):
        return f"<Rake {self.rakeId} ({'AC' if self.isAC else 'NON-AC'}, {self.rakeSize}-car)>"

class RakeCycle:
    def __init__(self, linkName):
        self.rake = None
        self.status = RakeLinkStatus.VALID

        self.linkName = linkName
        self.serviceIds = []
        self.undefinedIds = []
        self.startDepot = None
        self.endDepot = None

        self.servicePath = None

        self.render = True
        self.lengthKm = 0
        self.durationMinutes = 0

    def __repr__(self):
        rake_str = self.rake.rakeId if self.rake else 'Unassigned'
        n_services = len(self.servicePath)
        start = self.servicePath[0].events[0].atStation if self.servicePath else '?'
        end = self.servicePath[-1].events[-1].atStation if self.servicePath else '?'

        return f"<RakeCycle {self.linkName} ({n_services} services, {self.lengthKm}Km) {start}->{end}>"

class Service:
    '''Purely what can be extracted from a single column'''
    def __init__(self, type: ServiceType):
        self.rawServiceCol = None
        self.type = type
        self.zone = None
        self.serviceId = None
        self.direction = None
        self.line = None

        self.rakeLinkName = None
        self.rakeSizeReq = None
        self.needsACRake = False

        self.initStation = None
        self.linkedTo = None
        self.finalStation = None

        self.events = []

        self.activeDates = set(Day)
        self.render = True

        self.durationMinutes = 0
        self.lengthKm = 0


    def computeDurationMinutes(self):
        self.durationMinutes = self.events[-1].atTime - self.events[0].atTime

    def checkStartStationConstraint(self, qq):
        if not qq.startStation:
            return

        start = qq.startStation
        print(self.events)
        print(self)
        first = self.events[0].atStation

        t_first = self.events[0].atTime
        t_lower, t_upper = qq.inTimePeriod
        print(first)
        print(start)

        if first == start:
            if not (t_lower <= t_first <= t_upper):
                self.render = False
        else:
            self.render = False

    def checkEndStationConstraint(self, qq):
        if not qq.endStation:
            return

        end = qq.endStation
        last = self.events[-1].atStation
        t_last = self.events[-1].atTime
        t_lower, t_upper = qq.inTimePeriod

        if last == end:
            if not (t_lower <= t_last <= t_upper):
                self.render = False
        else:
            self.render = False

    def checkDirectionConstraint(self, qq):
        dir = qq.inDirection
        if not dir:
            return

        dirMatch = False
        for d in qq.inDirection:
            if d == "UP" and self.direction == Direction.UP:
                dirMatch = True
                break
            elif d == "DOWN" and self.direction == Direction.DOWN:
                dirMatch = True
                break

        if not dirMatch:
            self.render = False

    def checkACConstraint(self, qq):
        mode = qq.ac
        if not mode or mode == "all":
            return

        if mode == "ac" and not self.needsACRake:
            self.render = False
        elif mode == "nonac" and self.needsACRake:
            self.render = False

    def checkPassingThroughConstraint(self, qq):
        qPassingStns = [s.upper() for s in qq.passingThrough] if qq.passingThrough else []
        if not qPassingStns:
            return

        stnMapTimes = {}
        for e in self.events:
            if e.atStation not in stnMapTimes:
                stnMapTimes[e.atStation] = []
            stnMapTimes[e.atStation].append(e.atTime)

        for st in qPassingStns:
            if st not in stnMapTimes:
                self.render = False
                return

            t = stnMapTimes[st][-1]
            t_lower, t_upper = qq.inTimePeriod
            if not (t_lower <= t <= t_upper):
                self.render = False
                return

    def computeLengthKm(self):
        l = 0
        dprev = DISTANCE_MAP[self.events[0].atStation]
        for e in self.events[1:]:
            stName = e.atStation
            dCCGKm = DISTANCE_MAP[stName]
            d = abs(dprev - dCCGKm)
            l += d
            dprev = dCCGKm
        self.lengthKm = l

    def generateStationEvents(self, parser):
        sheet = None
        if self.direction == Direction.UP:
            sheet = parser.wttSheets[0]
        else:
            sheet = parser.wttSheets[1]

        stName = None
        serviceCol = self.rawServiceCol
        for rowIdx, cell in serviceCol.items():
            match = parser.rTimePattern.search(str(cell))
            if match:
                tCell = match.group(0)
                stName= sheet.iat[rowIdx, 0]
                if pd.isna(stName) or not str(stName).strip():
                    stName = sheet.iat[rowIdx - 1, 0]
                    if pd.isna(stName) or not str(stName).strip():
                        stName = sheet.iat[rowIdx - 2, 0]
                stName = normalize_station_name(stName)
                if str(stName).strip() in parser.stations.keys():
                    station = parser.stations[str(stName).strip()]
                elif "REVERSED" in str(stName).upper():
                    stName= sheet.iat[rowIdx - 1, 0]
                    if pd.isna(stName) or not str(stName).strip():
                        stName = sheet.iat[rowIdx - 2, 0]

                    stName = self.events[-1].atStation

                stName = stName.strip().upper()

                isATime = True if sheet.iat[rowIdx, 1] == "A" else False

                if isATime:
                    tArr = str(tCell).strip()
                    e1 = StationEvent(stName, self, tArr, EventType.ARRIVAL)
                    isDTime = True if sheet.iat[rowIdx+1, 1] == "D" else False
                    self.events.append(e1)
                    parser.eventsByStationMap[stName].append(e1)
                    if isDTime:
                        tDep = str(serviceCol.iloc[rowIdx + 1]).strip()
                        if parser.rTimePattern.match(tDep):
                            e2 = StationEvent(stName, self, tDep, EventType.DEPARTURE)
                            self.events.append(e2)
                            parser.eventsByStationMap[stName].append(e2)
                    else:
                        pass
                else:
                    time = str(tCell).strip()
                    e = StationEvent(stName, self, time, EventType.ARRIVAL)
                    self.events.append(e)
                    parser.eventsByStationMap[stName].append(e)

    def __repr__(self):
        sid = ','.join(str(s) for s in self.serviceId) if self.serviceId else 'None'
        dirn = self.direction.name if self.direction else 'NA'
        zone = self.zone.name if self.zone else 'NA'
        ac = 'AC' if self.needsACRake else 'NON-AC'
        rake = f"{self.rakeSizeReq}-CAR" if self.rakeSizeReq else '?'
        init = self.initStation.name if self.initStation else '?'
        final = self.finalStation.name if self.finalStation else '?'
        linked = self.linkedTo if self.linkedTo else 'None'

        return f"<Service {sid} ({dirn}, {zone}, {ac}, {rake}) {init}->{final} linked:{linked}>"

    def getLastStation(self):
        return self.stationPath[-1]

    def getFirstStation(self):
        return self.stationPath[0]

class StationEvent:
    def __init__(self, st, sv, time, type):
        self.atStation = st
        self.ofService = sv
        self.atTime = self._timeToMinutes(time)

        self.platform = None
        self.eType = None
        self.render = True

    def _timeToMinutes(self, time_str):
        '''Convert time string to minutes since midnight, with wrap-around.'''
        if not time_str:
            return None
        try:
            t = datetime.strptime(time_str.strip(), "%H:%M:%S")
        except ValueError:
            try:
                t = datetime.strptime(time_str.strip(), "%H:%M")
            except ValueError:
                return None

        minutes = t.hour * 60 + t.minute + t.second / 60
        if minutes < 165:  # 2:45 AM wrap-around
            minutes += 1440
        return minutes


class Station:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.large = False
        self.rakeHoldingCapacity = None
        self.events = {}
