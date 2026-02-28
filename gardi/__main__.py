import sys
import argparse
from gardi.simulator import Simulator


def run_server(args):
    sim = Simulator(debug=args.debug)
    sim.run(host=args.host, port=args.port)


def _parse_and_build(args):
    """Shared setup: parse WTT + summary, build rake cycles."""
    from gardi.core.parser import TimeTableParser
    parser = TimeTableParser(args.wtt_file, args.summary_file)
    parser.wtt.generateRakeCycles(parser)
    return parser


def _write_output(output, args):
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Written to {args.output}")
    else:
        print(output)


def run_analyze(args):
    if not (args.replace or args.graph_only or args.sample_traversal_times or args.timing_split or args.all_services):
        print("No analysis mode specified. Use --replace, --graph-only, --sample-traversal-times, --timing-split, or --all-services.")
        print("Run 'gardi analyze --help' for usage.")
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
        _write_output(format_report(report), args)

    elif args.graph_only:
        from gardi.core.replacement_analyzer import ReplacementAnalyzer

        ra = ReplacementAnalyzer(parser.wtt, parser)
        _write_output(ra.graph_summary(), args)

    elif args.sample_traversal_times:
        from gardi.core.analyzer import TraversalAnalyzer

        analyzer = TraversalAnalyzer()
        df, meta = analyzer.analyze(parser.wtt)

        header = (
            f"# Traversal Time Analysis\n"
            f"# Services sampled: {meta['total_services_sampled']}\n"
            f"# Station pairs: {meta['pair_count']}\n"
            f"# Pairs with <10 samples: {meta['pairs_with_low_samples']}\n"
        )
        _write_output(header + df.to_csv(index=False), args)

    elif args.timing_split:
        from gardi.core.analyzer import timing_split

        corridor = args.timing_split.split(",")
        if len(corridor) == 2:
            start, end = corridor[0].strip(), corridor[1].strip()
        else:
            start, end = "VIRAR", "CHURCHGATE"

        df, meta = timing_split(parser.wtt, start, end)

        header = (
            f"# Timing Split: {meta['corridor']}\n"
            f"# Services matched: {meta['services_matched']}\n"
        )
        _write_output(header + df.to_csv(index=False), args)

    elif args.all_services:
        from gardi.core.analyzer import all_services

        df, meta = all_services(parser.wtt)

        header = (
            f"# All Services\n"
            f"# Services: {meta['service_count']}\n"
        )
        _write_output(header + df.to_csv(index=False), args)



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
    analyze_parser.add_argument('wtt_file', help='Path to WTT Excel file')
    analyze_parser.add_argument('summary_file', help='Path to WTT Link Summary Excel file')
    analyze_parser.add_argument('-o', '--output', help='Output file (default: stdout)')

    mode = analyze_parser.add_mutually_exclusive_group()
    mode.add_argument('--replace', help='AC replacement analysis for given rakelinks (e.g. A,B,C)')
    mode.add_argument('--graph-only', action='store_true', help='Dump full rakelink followings graph')
    mode.add_argument('--sample-traversal-times', action='store_true', help='Inter-station run times from ServiceLeg data')
    mode.add_argument('--timing-split', nargs='?', const='VIRAR,CHURCHGATE', metavar='CORRIDOR',
                      help='Per-service corridor timings (default: VIRAR,CHURCHGATE)')
    mode.add_argument('--all-services', action='store_true',
                      help='List all services with line type and switching info')

    analyze_parser.add_argument('--station', help='With --replace, show arrival sequence at a station (e.g. DADAR)')
    analyze_parser.add_argument('--peak', action='store_true', help='With --station, restrict to peak hours only')

    args = top.parse_args()

    if args.command == 'view':
        run_server(args)
    elif args.command == 'analyze':
        run_analyze(args)
    else:
        top.print_help()


if __name__ == '__main__':
    main()
