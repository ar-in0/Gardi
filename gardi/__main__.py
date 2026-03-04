import sys
import os
import argparse
from gardi.simulator import Simulator

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
DEFAULT_WTT = os.path.join(_DATA_DIR, 'SWTT-78_ADDITIONAL_AC_SERVICES_27_NOV_2024-1.xlsx')
DEFAULT_SUMMARY = os.path.join(_DATA_DIR, 'LINK_SWTT_78_UPDATED_05.11.2024-4.xlsx')


def run_server(args):
    sim = Simulator(debug=args.debug)
    sim.run(host=args.host, port=args.port)


def _parse_and_build(args):
    """Shared setup: parse WTT + summary, build rake cycles."""
    from gardi.core.parser import TimeTableParser
    parser = TimeTableParser(args.wtt_file, args.summary_file)
    parser.wtt.generateRakeCycles(parser)
    return parser


def _write_output(output, args, auto_name=None):
    dest = args.output
    if dest == "auto":
        if not auto_name:
            print("Error: no auto-name defined for this report.")
            sys.exit(1)
        dest = auto_name

    if dest:
        with open(dest, 'w') as f:
            f.write(output)
        print(f"Written to {dest}")
    else:
        print(output)


def run_analyze(args):
    if not (args.replace or args.graph_only or args.turnaround):
        print("No analysis mode specified. Use --replace, --graph-only, or --turnaround.")
        sys.exit(1)

    parser = _parse_and_build(args)

    if args.replace:
        from gardi.core.replacement_analyzer import ReplacementAnalyzer, format_report

        ra = ReplacementAnalyzer(parser.wtt, parser)
        replacement_set = [s.strip().upper() for s in args.replace.split(",")]

        unknown = [name for name in replacement_set if name not in ra.rc_by_name]
        if unknown:
            print(f"Error: unknown rakelink(s): {', '.join(unknown)}")
            print(f"Available links: {', '.join(sorted(ra.rc_by_name.keys()))}")
            sys.exit(1)

        report = ra.evaluate(replacement_set, peak_only=args.peak, station=args.station)
        auto = f"replace_{'_'.join(replacement_set).lower()}.txt"
        _write_output(format_report(report), args, auto_name=auto)

    elif args.graph_only:
        from gardi.core.replacement_analyzer import ReplacementAnalyzer

        ra = ReplacementAnalyzer(parser.wtt, parser)
        _write_output(ra.graph_summary(), args, auto_name="rakelink_graph.txt")

    elif args.turnaround:
        from gardi.core.csv_builder import CsvBuilder

        if not args.station:
            print("Error: --station is required for --turnaround.")
            sys.exit(1)
        builder = CsvBuilder()
        output = builder.turnaround(parser.wtt, args.station)
        _write_output(output, args, auto_name=f"turnaround_{args.station.lower()}.csv")


def runCsv(args):
    from gardi.core.csv_builder import CsvBuilder

    parser = _parse_and_build(args)
    builder = CsvBuilder()

    if args.report_type == "sectional-times":
        output = builder.traversalTimes(parser.wtt)
        auto = "sectional_times.csv"
    elif args.report_type == "service-runtimes":
        corridor = args.corridor.split(",")
        if len(corridor) == 2:
            start, end = corridor[0].strip(), corridor[1].strip()
        else:
            start, end = "VIRAR", "CHURCHGATE"
        output = builder.timingSplit(parser.wtt, start, end)
        auto = f"service_runtimes_{start.lower()}_{end.lower()}.csv"
    elif args.report_type == "service-switches":
        output = builder.allServices(parser.wtt)
        auto = "service_switches.csv"

    _write_output(output, args, auto_name=auto)


def main():
    top = argparse.ArgumentParser(
        description='Gardi Railway Timetable Visualization',
        prog='gardi'
    )
    subparsers = top.add_subparsers(dest='command')

    # view subcommand
    view_parser = subparsers.add_parser('view', help='Launch interactive visualization server')
    view_parser.add_argument('--host', default='127.0.0.1', help='Host to run on')
    view_parser.add_argument('--port', default=8051, type=int, help='Port to run on')
    view_parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    # analyze subcommand
    analyze_parser = subparsers.add_parser('analyze', help='WTT analysis tools')
    analyze_parser.add_argument('wtt_file', nargs='?', default=DEFAULT_WTT, help='Path to WTT Excel file (default: data/)')
    analyze_parser.add_argument('summary_file', nargs='?', default=DEFAULT_SUMMARY, help='Path to WTT Link Summary Excel file (default: data/)')
    analyze_parser.add_argument('-o', '--output', help='Output file (default: stdout)')

    mode = analyze_parser.add_mutually_exclusive_group()
    mode.add_argument('--replace', help='AC replacement analysis for given rakelinks (e.g. A,B,C)')
    mode.add_argument('--graph-only', action='store_true', help='Dump full rakelink followings graph')
    mode.add_argument('--turnaround', action='store_true', help='Turnaround time distribution at a station (requires --station)')

    analyze_parser.add_argument('--station', help='Station name (e.g. DADAR). Used with --replace or --turnaround')
    analyze_parser.add_argument('--peak', action='store_true', help='With --replace --station, restrict to peak hours only')

    # csv subcommand
    csv_parser = subparsers.add_parser(
        'csv', help='CSV data exports',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "report types:\n"
            "  sectional-times   Median run time between adjacent station pairs, by direction\n"
            "  service-runtimes  Per-service corridor timing: start, end, duration (use --corridor)\n"
            "  service-switches  All services with line type, direction, and line-switch stations"
        ),
    )
    csv_parser.add_argument('wtt_file', nargs='?', default=DEFAULT_WTT, help='Path to WTT Excel file (default: data/)')
    csv_parser.add_argument('summary_file', nargs='?', default=DEFAULT_SUMMARY, help='Path to WTT Link Summary Excel file (default: data/)')
    csv_parser.add_argument('report_type', choices=['sectional-times', 'service-runtimes', 'service-switches'],
                            help='Type of CSV report to generate')
    csv_parser.add_argument('-o', '--output', help='Output file (default: stdout)')
    csv_parser.add_argument('--corridor', default='VIRAR,CHURCHGATE',
                            help='Start,End stations for service-runtimes (default: VIRAR,CHURCHGATE)')

    args = top.parse_args()

    if args.command == 'view':
        run_server(args)
    elif args.command == 'analyze':
        run_analyze(args)
    elif args.command == 'csv':
        runCsv(args)
    else:
        top.print_help()


if __name__ == '__main__':
    main()
