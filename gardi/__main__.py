import sys
import argparse
from gardi.simulator import Simulator


def main():
    parser = argparse.ArgumentParser(
        description='Gardi Railway Timetable Visualization',
        prog='gardi'
    )
    parser.add_argument('--host', default='127.0.0.1', help='Host to run on')
    parser.add_argument('--port', default=8051, type=int, help='Port to run on')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    # Create and run simulator
    sim = Simulator(debug=args.debug)

    # calls Dash app run()
    sim.run(host=args.host, port=args.port)

if __name__ == '__main__':
    main()
