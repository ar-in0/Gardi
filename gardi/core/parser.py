# gardi/core/parser.py

import re
import time
import pandas as pd

from collections import defaultdict
from gardi.core.models import (
    TimeTable, RakeCycle, Service, Station,
    RakeLinkStatus, ServiceType, ServiceZone, Direction, Day, Line,
    DISTANCE_MAP, SERVICE_ID_LEN, normalize_station_name
)

class TimeTableParser:
    rCentralRailwaysPattern = re.compile(r'^[Cc]\.\s*[Rr][Ll][Yy]\.?$')
    rTimePattern = re.compile(
        r'(?:\d{1,2}/\d{1,2}/\d{2,4}\s+)?'   # optional date prefix
        r'(?P<time>[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$'  # capture only time
    )
    rServiceIDPattern = re.compile(r'^\s*\d{5}(?:\b.*)?$', re.IGNORECASE)
    rLinkNamePattern = re.compile(r'^\s*([A-Z]{1,2})\s*(?:\u2020)?\s*$', re.UNICODE) # only match A AK with dagger, i.e. start links
    rEtyPattern = re.compile(r'\bETY\s*\d+\b', re.IGNORECASE)
    rLineMarkerPattern = re.compile(r'^(?:(\d)/)?([TL])(?:H)?$', re.IGNORECASE)
    # Matches: T, L, TH, 5/L, 6/T, 3/L etc. Group 1=platform, Group 2=T or L

    # Keep distanceMap as class attribute (immutable reference)
    distanceMap = DISTANCE_MAP

    def __init__(self, fpWttXlsx=None, fpWttSummaryXlsx=None):
        self.wtt = TimeTable()
        self.stationCol = None # df column with stations

        self.wttSheets = []
        self.eventsByStationMap = defaultdict(list)
        self.stations = {}
        self.stationMap = {}

        # if the req comes from a local test
        # i.e. python3 timetable.py
        if fpWttSummaryXlsx and fpWttXlsx:
            self.xlsxToDf(fpWttXlsx)
            self.registerStations()
            self.registerServices()

            # get timing information too
            # WTT services must be fully populated
            # before starting the summary-sheet parse.

            # parse summary sheet
            # generate rakelink summary
            self.parseWttSummary(fpWttSummaryXlsx)

            self.wtt.suburbanServices = self.isolateSuburbanServices()

    @classmethod
    def fromFileObjects(cls, wttFileObj, summaryFileObj):
        '''Create TimeTableParser from BytesIO objects for uploaded files'''
        instance = cls()
        start = time.time()
        instance.xlsxToDfFromFileObj(wttFileObj)
        instance.registerStations()
        end = time.time()

        # this can be triggered when the
        # summary sheet is uploaded
        instance.registerServices()
        print(f"time in: {end - start}")
        instance.parseWttSummaryFromFileObj(summaryFileObj) # creates rakecycles without timing info
        instance.wtt.suburbanServices = instance.isolateSuburbanServices()
        return instance

    def xlsxToDfFromFileObj(self, fileObj):
        '''Parse Excel from file object instead of path'''
        xlsx = pd.ExcelFile(fileObj)
        for sheet in xlsx.sheet_names:
            df = xlsx.parse(sheet, skiprows=4).dropna(axis=1, how='all')
            self.wttSheets.append(df)

        self.upSheet = self.wttSheets[0]
        self.downSheet = self.wttSheets[1]

    def parseWttSummaryFromFileObj(self, fileObj):
        '''Parse summary Excel from file object instead of path'''
        xlsx = pd.ExcelFile(fileObj)
        summarySheet = xlsx.sheet_names[0]
        self.wttSummarySheet = xlsx.parse(summarySheet, skiprows=2).dropna(axis=0, how="all")
        self.parseRakeLinks(self.wttSummarySheet)

    def isolateSuburbanServices(self):
        suburbanIds = set()
        seen, repeated = set(), set()
        for rc in self.wtt.rakecycles:
            suburbanIds.update(rc.serviceIds)
            s = set(rc.serviceIds)
            repeated |= seen & s
            seen |= s

        suburbanServices = []
        for s in (self.wtt.upServices + self.wtt.downServices):
            if any(sid in suburbanIds for sid in s.serviceId):
                suburbanServices.append(s)

        print(f"\nSuburban services identified: {len(suburbanServices)} / {len(self.wtt.upServices) + len(self.wtt.downServices)}")
        return suburbanServices

    # timetable.py -> class TimeTableParser
    def parseRakeLinks(self, sheet):
        allServices = self.wtt.upServices + self.wtt.downServices
        sheet = sheet.reset_index(drop=True)

        for i in range(len(sheet)):
            sIDRow = sheet.iloc[i]

            # check for linkname
            if pd.isna(sIDRow.iloc[1]):
                continue

            linkName = str(sIDRow.iloc[1]).strip().upper()
            if not TimeTableParser.rLinkNamePattern.match(linkName):
                continue

            # Identify the speed row (FAST/SLOW is 2 rows below Service IDs)
            lineRow = None
            if i + 2 < len(sheet):
                lineRow = sheet.iloc[i + 2]

            # collect all valid service IDs and their corresponding speed labels
            # We store them as pairs to maintain the column association
            service_entries = []

            # Use enumerate to keep track of column indices relative to iloc[2:]
            for col_offset, cell in enumerate(sIDRow.iloc[2:]):
                if pd.isna(cell):
                    continue
                cell = str(cell)

                if TimeTableParser.isServiceID(cell):
                    # --- Existing extraction logic ---
                    matchEty = TimeTableParser.rEtyPattern.search(cell)
                    if matchEty:
                        sid_val = matchEty.group(0)
                    else:
                        digit_match = re.search(r'\d+', cell)
                        sid_val = int(digit_match.group()) if digit_match else cell

                    # ---  line Extraction Logic ---
                    line_label = None
                    if lineRow is not None:
                        # Absolute column index is col_offset + 2
                        raw_line = lineRow.iloc[col_offset + 2]
                        if not pd.isna(raw_line):
                            val = str(raw_line).strip()
                            # Mark with label if match, else store raw string
                            if val.upper() in ["FAST", "SLOW"]:
                                line_label = val.upper()
                            else:
                                if "FAST" in val.upper() or "SLOW" in val.upper():
                                    line_label = val


                    service_entries.append((sid_val, line_label))

            if not service_entries:
                continue

            rc = RakeCycle(linkName)

            for sid, speed in service_entries:
                rc.serviceIds.append(sid)
                service = next((s for s in allServices if str(sid) in str(s.serviceId)), None)
                if service:
                    service.rakeLinkName = linkName
                    if service.line is None:  # SWTT markers take priority
                        if speed == "FAST":
                            service.line = Line.THROUGH
                        elif speed == "SLOW":
                            service.line = Line.LOCAL
                else:
                    rc.undefinedIds.append((linkName, sid))

            self.wtt.rakecycles.append(rc)

        # summary
        if 'rc' in locals() and rc.undefinedIds:
            print(f"\n{len(rc.undefinedIds)} service IDs from summary sheet not found in detailed WTT:")
            for linkName, sid in rc.undefinedIds:
                print(f" ** Link {linkName}: Service {sid}")
        elif 'rc' in locals():
            print("\nAll rake link service IDs successfully matched with WTT services.")


    def parseWttSummary(self, filePathXlsx):
        xlsx = pd.ExcelFile(filePathXlsx)
        summarySheet = xlsx.sheet_names[0]
        self.wttSummarySheet = xlsx.parse(summarySheet, skiprows=2).dropna(axis=0, how="all") # drop fully blank rows

        self.parseRakeLinks(self.wttSummarySheet)

    def xlsxToDf(self, filePathXlsx):
        xlsx = pd.ExcelFile(filePathXlsx)
        for sheet in xlsx.sheet_names:
            # First row is blank, followed by the station row # onwards
            # with skipped=4. skipped=5 removes the extra white row above the main content.
            df = xlsx.parse(sheet, skiprows=4).dropna(axis=1, how='all')
            self.wttSheets.append(df)
            # remove fully blank columns

        self.upSheet = self.wttSheets[0]
        self.downSheet = self.wttSheets[1]

    # always use cleancol before working with a column
    def cleanCol(self, sheet, colIdx):
        '''Return the column as-is unless it is entirely NaN or whitespace.'''
        clean = sheet.iloc[:, colIdx].astype(str)

        # Check if all entries are NaN or whitespace (after conversion to str)
        if clean.isna().all() or clean.str.fullmatch(r'(nan|\s*)', na=False).all():
            return pd.Series(dtype=str)

        return clean

    def registerStations(self):
        '''Create an object corresponding to every station on the network'''
        sheet = self.upSheet # a dataframe
        self.stationCol = sheet.iloc[:, 0]

        for idx, rawVal in enumerate(self.stationCol[1:-8]): # to skip the linkage line + nans
            if pd.isna(rawVal):
                continue
            stName = str(rawVal).strip()
            if not stName:
                continue

            st = Station(idx, stName.upper())
            self.wtt.stations[st.name] = st

            st.dCCGkm = DISTANCE_MAP[st.name]

        # create station map
        self.stationMap = {
            "BDTS": self.wtt.stations["BANDRA"],
            "BA": self.wtt.stations["BANDRA"],
            "MM": self.wtt.stations["MAHIM JN."],
            "ADH": self.wtt.stations["ANDHERI"],
            "KILE": self.wtt.stations["KANDIVALI"],
            "BSR": self.wtt.stations["BHAYANDAR"],
            "DDR": self.wtt.stations["DADAR"],
            "VR": self.wtt.stations["VIRAR"],
            "BVI": self.wtt.stations["BORIVALI"],
            "CSTM": Station(43, "CHATTRAPATI SHIVAJI MAHARAJ TERMINUS"),
            "CSMT": Station(44, "CHATTRAPATI SHIVAJI MAHARAJ TERMINUS"),
            "PNVL": Station(45, "PANVEL"),
            "MX": self.wtt.stations["MAHALAKSHMI"]
        }

        self.stations = self.wtt.stations

    # First station with a valid time
    # "EX ..."
    # else First station in Stations i.e. VIRAR
    def extractInitStation(self, serviceCol, sheet):
        '''Determines the first arrival station in the service path.
        serviceCol: pandas.Series
        sheet: pandas.Dataframe'''
        stationName = None
        for rowIdx, cell in serviceCol.items():
            if TimeTableParser.rTimePattern.match(cell):
                stationName = sheet.iat[rowIdx, 0]

                if pd.isna(stationName) or not str(stationName).strip():
                    # check row above if possible
                    if rowIdx > 0:
                        stationName = sheet.iat[rowIdx - 1, 0]
                break

        if pd.isna(stationName) or not str(stationName).strip():
            raise ValueError(f"Invalid station name near row {rowIdx}")

        stationName = normalize_station_name(stationName)

        station = self.wtt.stations[stationName.strip().upper()]
        if not station:
            raise ValueError(f"No station found for '{stationName}'")
        return station

    def extractFinalStation(self, serviceCol, sheet):
        abbrStations = self.stationMap.keys()
        station = None
        arrlRowIdx = None

        # Find the "ARR" / "ARRL." marker first
        for rowIdx, cell in serviceCol.items():
            cellStr = str(cell).strip().upper()
            if re.search(r'\bARRL?\.?\b', cellStr, flags=re.IGNORECASE):
                arrlRowIdx = rowIdx
                break

        # If arrl not found:
        if not arrlRowIdx:
            for rowIdx in reversed(serviceCol.index):
                cell = str(serviceCol.iloc[rowIdx]).strip()
                if TimeTableParser.rTimePattern.match(cell):
                    stName= sheet.iat[rowIdx, 0]
                    if pd.isna(stName) or not str(stName).strip():
                        stName = sheet.iat[rowIdx - 1, 0]
                        if pd.isna(stName) or not str(stName).strip():
                            stName = sheet.iat[rowIdx - 2, 0]
                    stName = normalize_station_name(stName)
                    if str(stName).strip() in self.wtt.stations.keys():
                        station = self.wtt.stations[str(stName).strip()]
                        return station
                    elif "REVERSED" in str(stName).upper():
                        stName= sheet.iat[rowIdx - 1, 0]
                        if pd.isna(stName) or not str(stName).strip():
                            stName = sheet.iat[rowIdx - 2, 0]
                        station = self.wtt.stations[str(stName).strip()]
                        return station

            return station

        # arrl found, now look in nearby cells for a station
        nearbyRows = [arrlRowIdx]
        if arrlRowIdx > 0:
            nearbyRows.append(arrlRowIdx - 1)
        if arrlRowIdx < len(serviceCol) - 1:
            nearbyRows.append(arrlRowIdx + 1)

        stationName = None
        for r in nearbyRows:
            cellVal = str(serviceCol.iloc[r]).strip().upper()
            if not cellVal or cellVal == 'NAN':
                continue

            for stKey in abbrStations:
                if stKey in cellVal:
                    stationName = stKey
                    break

            if stationName:
                station = self.stationMap[stationName]
                return station


    def extractInitialDepot(self, serviceID):
        '''Every service must start at some yard/carshed. These
        are specified in the WTT-Summary Sheet.'''
        pass

    def extractLinkedToNext(self, serviceCol, direction):
        '''Find the linked service (if any) following a 'Reversed as' entry.'''
        serviceCol = serviceCol.dropna()
        mask = self.stationCol.str.contains("Reversed as", case=False, na=False)
        match = self.stationCol[mask]

        if match.empty:
            return None

        rowIdx = match.index[0]

        # Guard
        if rowIdx not in serviceCol.index:
            return None

        if (direction == Direction.UP):
            depTime = serviceCol.loc[rowIdx]
            linkedService = serviceCol.loc[rowIdx + 1]
        else:
            depTime = serviceCol.loc[rowIdx -1]
            linkedService = serviceCol.loc[rowIdx]

        # Convert safely, handle NaN/None/float cases
        if pd.isna(linkedService) or pd.isna(depTime):
            return None

        depTime = str(depTime).strip()
        linkedService = str(linkedService).strip()

        # Skip empty, non-sid
        match = linkedService.isdigit() and len(linkedService) == SERVICE_ID_LEN
        if not depTime or depTime.lower() == "nan" or not linkedService or linkedService.lower() == "nan" or not match:
            linkedService = None

        return linkedService

    @staticmethod
    def isServiceID(cell): # cell must be str
        if not cell or cell.strip().lower() == "nan":
            return False
        return bool(
            TimeTableParser.rServiceIDPattern.match(cell) or
            TimeTableParser.rEtyPattern.search(cell)
            )

    # @staticmethod
    def isRakeLinkName(cell):
        if not cell or cell.strip().lower() == "nan":
            return False

        match = TimeTableParser.rLinkNamePattern.match(cell)
        if match:
            return True

    @staticmethod
    def extractServiceHeader(serviceCol):
        '''Extract service ID and Rake size and zone requirement'''
        idRegion =  serviceCol[:6]
        ids = []
        rakeSize = 15 # default size
        zone = None
        for cell in idRegion: # cell contents are always str
            cell = cell.strip()
            if TimeTableParser.rCentralRailwaysPattern.match(cell):
                zone = ServiceZone.CENTRAL

            if TimeTableParser.isServiceID(cell):
                matchEty = TimeTableParser.rEtyPattern.search(cell)
                if matchEty:
                    ids.append(matchEty.group(0))
                else:
                    ids.append(int(re.search(r'\d+', cell).group()))
                    if (cell.startswith("9")):
                        zone = ServiceZone.SUBURBAN

            linkName = None

            if "CAR" in cell.upper():
                match = re.search(r'(12|15|20|10)\s*CAR', cell, flags=re.IGNORECASE)
                if match is None:
                    raise ValueError(f"Failed to extract rake size from '{cell}'")
                rakeSize = int(match.group(1))

        return ids, rakeSize, zone, linkName

    @staticmethod
    def extractACRequirement(serviceCol):
        isAC = -1
        for cell in serviceCol:
            cell = cell.strip()
            if (isAC == 1): return True
            if ("Air" in cell or "Condition" in cell or "AC" in cell):
                isAC += 1
        return False

    @staticmethod
    def extractActiveDates(serviceCol):
        pass

    def extractLineMarkers(self, serviceCol, sheet):
        """Extract T/L line markers from a service column.
        Returns list of (station_name, Line) tuples."""
        markers = []
        for rowIdx, cell in serviceCol.items():
            cell_str = str(cell).strip()
            if not cell_str or cell_str.lower() == 'nan':
                continue

            line_type = None
            match = TimeTableParser.rLineMarkerPattern.match(cell_str)
            if match:
                code = match.group(2).upper()
                line_type = Line.THROUGH if code == 'T' else Line.LOCAL
            elif cell_str.upper() == 'O/L':
                line_type = Line.LOCAL

            if line_type is None:
                continue

            # Resolve station name (walk up rows if blank, same as extractInitStation)
            stName = sheet.iat[rowIdx, 0]
            if pd.isna(stName) or not str(stName).strip():
                if rowIdx > 0:
                    stName = sheet.iat[rowIdx - 1, 0]
                if pd.isna(stName) or not str(stName).strip():
                    if rowIdx > 1:
                        stName = sheet.iat[rowIdx - 2, 0]
            if pd.isna(stName) or not str(stName).strip():
                continue

            stName = normalize_station_name(str(stName).strip().upper())
            if stName.upper() == 'STATIONS':
                continue
            markers.append((stName, line_type))

        return markers

    def doRegisterServices(self, sheet, direction, numCols):
        serviceCols = sheet.columns
        for col in serviceCols[2:numCols]:
            idx = serviceCols.get_loc(col)
            clean = self.cleanCol(sheet, idx)
            if (clean.empty):
                continue
            # skip repeat STATION columns
            if (not clean.empty and clean.iloc[0].strip().upper() == "STATIONS"):
                continue

            # check for an ADAD column
            vals = clean.dropna().astype(str).str.strip().str.upper().tolist()
            isADAD = any(a == "A" and b == "D" for a, b in zip(vals, vals[1:]))
            if(isADAD):
                continue

            # if we are here, the column is a service column
            service = Service(ServiceType.REGULAR)
            service.direction = direction
            service.rawServiceCol = clean

            sIds, rakeSize, zone, linkName = TimeTableParser.extractServiceHeader(clean)
            if (not len(sIds)):
                service.type = ServiceType.STABLING
            if (len(sIds) > 1):
                service.type = ServiceType.MULTI_SERVICE

            service.serviceId = sIds
            service.rakeSizeReq = rakeSize
            service.zone = zone

            service.needsACRake = TimeTableParser.extractACRequirement(clean)

            service.initStation = self.extractInitStation(clean, sheet)

            service.finalStation = self.extractFinalStation(clean, sheet)

            service.linkedTo = self.extractLinkedToNext(clean, direction)

            markers = self.extractLineMarkers(clean, sheet)
            if markers:
                service.lineSegments = markers
                lines_used = set(m[1] for m in markers)
                if len(lines_used) > 1:
                    service.line = Line.SEMI_FAST
                else:
                    service.line = markers[0][1]

            if direction == Direction.UP:
                self.wtt.upServices.append(service)
            elif direction == Direction.DOWN:
                self.wtt.downServices.append(service)
            else:
                print("No other possibility")

    def registerServices(self):
        '''Enumerate every possible service, extract arrival-departure timings. Populate
        the Station events. For now, store up and down services seperately
        '''
        UP_TT_COLUMNS = 949
        upSheet = self.upSheet
        self.doRegisterServices(upSheet, Direction.UP, UP_TT_COLUMNS)

        downSheet = self.downSheet
        DOWN_TT_COLUMNS = 982
        self.doRegisterServices(downSheet, Direction.DOWN, DOWN_TT_COLUMNS)


if __name__ == "__main__":
    wttPath = "/home/armaan/Fun-CS/IITB-RAILWAYS-2025/western-railways-simulator/SWTT-78_ADDITIONAL_AC_SERVICES_27_NOV_2024-1.xlsx"
    wttSummaryPath = "/home/armaan/Fun-CS/IITB-RAILWAYS-2025/western-railways-simulator/LINK_SWTT_78_UPDATED_05.11.2024-4.xlsx"
    parsed = TimeTableParser(wttPath, wttSummaryPath)

    parsed.wtt.generateRakeCycles(parsed)

    parsed.wtt.printStatistics()
