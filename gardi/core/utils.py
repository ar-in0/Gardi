# utils.py — AC/NAC mixing analysis helpers

from gardi.core.parser import TimeTableParser

# event + sequence helpers

def getCorridorStations(start, end, distanceMap):
    '''
    Return ordered list of stations from start -> end using distanceMap.
    Direction is automatically handled.
    '''
    stations = sorted(distanceMap.keys(), key=lambda s: distanceMap[s])

    if start not in stations or end not in stations:
        raise ValueError(f'Invalid station(s): {start}, {end}')

    i_start = stations.index(start)
    i_end = stations.index(end)

    if i_start <= i_end:
        return stations[i_start:i_end + 1]

    return stations[i_end:i_start + 1][::-1]


def getStationEvents(station, t_lower, t_upper):
    '''
    Return station events in [t_lower, t_upper], sorted by atTime.
    '''
    events = TimeTableParser.eventsByStationMap.get(station, [])
    evs = [e for e in events if e.atTime is not None and t_lower <= e.atTime <= t_upper]
    evs.sort(key=lambda e: e.atTime)
    return evs


def getStationSequence(events):
    '''
    Convert events -> binary sequence.
    1 = AC, 0 = non-AC.
    '''
    seq = []
    for e in events:
        svc = e.ofService
        is_ac = getattr(svc, 'needsACRake', False)
        seq.append(1 if is_ac else 0)
    return seq


# core sequence math

def countAlternations(seq):
    '''
    Count number of adjacent flips (1->0 or 0->1).
    '''
    return sum(1 for a, b in zip(seq, seq[1:]) if a != b)


def computeRunLengths(seq):
    '''
    Return list of run lengths of identical consecutive values.
    Example: [1,1,0,0,0,1] -> [2,3,1]
    '''
    if not seq:
        return []

    runs = []
    cur = seq[0]
    cur_len = 1

    for x in seq[1:]:
        if x == cur:
            cur_len += 1
        else:
            runs.append(cur_len)
            cur = x
            cur_len = 1

    runs.append(cur_len)
    return runs


def maxRunLength(run_lengths):
    '''
    Return the maximum run length.
    '''
    return max(run_lengths) if run_lengths else 0


def meanRunLength(run_lengths):
    '''
    Mean run length.
    '''
    return (sum(run_lengths) / len(run_lengths)) if run_lengths else 0.0


def idealMaxRun(n_ac, n_nonac):
    '''
    Best possible (minimal) max run length for given AC/NonAC counts.
    Formula: ceil(max(a,b) / (min(a,b) + 1))
    '''
    import math
    a = max(n_ac, n_nonac)
    b = min(n_ac, n_nonac)
    return math.ceil(a / (b + 1)) if b > 0 else a


def idealAlternations(n_ac, n_nonac, n):
    '''
    Maximum achievable alternations for given counts.
    '''
    if abs(n_ac - n_nonac) <= 1:
        return n - 1
    return 2 * min(n_ac, n_nonac)


def expectedAlternations(n_ac, n):
    '''
    Expected alternations under random shuffling of the sequence.
    p = AC proportion
    Expected = (n-1) * 2*p*(1-p)
    '''
    if n <= 1:
        return 0.0
    p = n_ac / n
    return (n - 1) * 2 * p * (1 - p)


def mixingScore(observed_alts, expected_alts, ideal_alts):
    '''
    Normalize mixing: 0 = random, 1 = best possible.
    Clamped to [0,1] (fallback to 0 where denom ~ 0).
    '''
    denom = ideal_alts - expected_alts
    if denom <= 1e-9:
        return 0.0
    score = float((observed_alts - expected_alts) / denom)
    # do not force clamp here; calling code can interpret values <0 or >1 if needed
    return score


# high-level analysis

def analyzeSequence(seq):
    '''
    Compute mixing metrics from a binary sequence.
    Returns a dict with counts, alternations, run stats and a mixing score.
    '''
    n = len(seq)
    if n == 0:
        return {'n': 0, 'status': 'empty'}
    if n == 1:
        return {
            'n': 1,
            'n_ac': seq[0],
            'n_nonac': 1 - seq[0],
            'status': 'insufficient_data'
        }

    n_ac = sum(seq)
    n_nonac = n - n_ac

    alts = countAlternations(seq)
    altr = alts / (n - 1)

    runs = computeRunLengths(seq)
    mx_run = maxRunLength(runs)
    mn_run = meanRunLength(runs)

    ideal_mx = idealMaxRun(n_ac, n_nonac)
    ideal_alts = idealAlternations(n_ac, n_nonac, n)
    exp_alts = expectedAlternations(n_ac, n)

    score = mixingScore(alts, exp_alts, ideal_alts)

    return {
        'n': n,
        'n_ac': n_ac,
        'n_nonac': n_nonac,
        'alternations': alts,
        'alternation_ratio': altr,
        'run_lengths': runs,
        'max_run_length': mx_run,
        'mean_run_length': mn_run,
        'ideal_max_run': ideal_mx,
        'ideal_alternation_ratio': (ideal_alts / (n - 1)) if n > 1 else 0.0,
        'mixing_score': score,
        'status': 'ok'
    }


# reporting helpers

def stationMixingReport(station, t_lower, t_upper):
    '''
    Compute full mixing report for a station in the given time window.
    Returns a list of per-station metric dicts across the ANDHERI->CHURCHGATE corridor.
    '''
    stations = getCorridorStations('ANDHERI', 'CHURCHGATE', TimeTableParser.distanceMap)
    metricslist = []

    for st in stations:
        events = getStationEvents(st, t_lower, t_upper)
        seq = getStationSequence(events)
        metrics = analyzeSequence(seq)

        metrics['station'] = st
        metrics['t_lower'] = t_lower
        metrics['t_upper'] = t_upper

        flags = []
        if metrics.get('status') == 'ok':
            score = metrics['mixing_score']
            if score >= 0.75:
                flags.append('good')
            elif score >= 0.5:
                flags.append('ok')
            else:
                flags.append('poor')

            if metrics['max_run_length'] > 2 * metrics['ideal_max_run']:
                flags.append('long_run_warning')

        metrics['flags'] = flags
        metricslist.append(metrics)

    return metricslist


def corridorMixingMinimal(start_station, end_station, t_lower, t_upper):
    '''
    Return a minimal mixing report for corridor analysis:
    per-station mixing_score, alternation_ratio, ideal_alternation_ratio.
    '''
    if not start_station or not end_station:
        start_station = 'ANDHERI'
        end_station = 'CHURCHGATE'

    distanceMap = TimeTableParser.distanceMap
    stations = getCorridorStations(start_station, end_station, distanceMap)
    result = []

    for s in stations:
        events = getStationEvents(s, t_lower, t_upper)
        seq = getStationSequence(events)
        m = analyzeSequence(seq)

        if m.get('status') != 'ok':
            result.append({
                'station': s,
                'mixing_score': None,
                'alternation_ratio': None,
                'ideal_alternation_ratio': None
            })
        else:
            result.append({
                'station': s,
                'mixing_score': m['mixing_score'],
                'alternation_ratio': m['alternation_ratio'],
                'ideal_alternation_ratio': m['ideal_alternation_ratio']
            })

    return result
