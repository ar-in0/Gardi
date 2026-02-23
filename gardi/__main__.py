import sys
import argparse
from gardi.simulator import Simulator


def run_server(args):
    sim = Simulator(debug=args.debug)
    sim.run(host=args.host, port=args.port)


def run_analyze(args):
    from gardi.core.parser import TimeTableParser
    from gardi.core.analyzer import TraversalAnalyzer

    parser = TimeTableParser(args.wtt_file, args.summary_file)
    parser.wtt.generateRakeCycles(parser)
    parser.wtt.suburbanServices = parser.isolateSuburbanServices()

    analyzer = TraversalAnalyzer()
    df, meta = analyzer.analyze(parser.wtt)

    header = (
        f"# Traversal Time Analysis\n"
        f"# Services sampled: {meta['total_services_sampled']}\n"
        f"# Station pairs: {meta['pair_count']}\n"
        f"# Pairs with <10 samples: {meta['pairs_with_low_samples']}\n"
    )
    csv_output = header + df.to_csv(index=False)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(csv_output)
        print(f"Written to {args.output}")
    else:
        print(csv_output)


def main():
    parser = argparse.ArgumentParser(
        description='Gardi Railway Timetable Visualization',
        prog='gardi'
    )
    subparsers = parser.add_subparsers(dest='command')

    # Default server options (also work without subcommand)
    parser.add_argument('--host', default='127.0.0.1', help='Host to run on')
    parser.add_argument('--port', default=8051, type=int, help='Port to run on')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    # analyze subcommand
    analyze_parser = subparsers.add_parser('analyze', help='Analyze inter-station traversal times')
    analyze_parser.add_argument('wtt_file', help='Path to WTT Excel file')
    analyze_parser.add_argument('summary_file', help='Path to WTT Link Summary Excel file')
    analyze_parser.add_argument('-o', '--output', help='Output CSV file (default: stdout)')

    args = parser.parse_args()

    if args.command == 'analyze':
        run_analyze(args)
    else:
        run_server(args)


if __name__ == '__main__':
    main()
