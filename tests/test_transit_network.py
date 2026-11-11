import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from agent.tools import transit_network as transit


def graph(edges, nodes=('A', 'B', 'C', 'D')):
    return {'directed': True, 'nodes': [{'id': n} for n in nodes], 'edges': edges}


def link(a, b, duration, **extra):
    return {'source': a, 'target': b, 'time_seconds': duration, 'mode': 'walk', **extra}


def ride(a, b, start, end, trip, **extra):
    return link(a, b, end-start, mode='bus', departure_seconds=start, arrival_seconds=end, trip_id=trip, **extra)


class NetworkToolsTests(unittest.TestCase):
    def test_weighted_path_uses_travel_time_not_distance(self):
        g = graph([link('A', 'D', 90, distance_m=10), link('A', 'B', 10, distance_m=20), link('B', 'D', 20, distance_m=20)])
        params = {'graph': g, 'origin': 'A', 'destination': 'D'}
        self.assertEqual(transit.shortest_path(params)['nodes'], ['A', 'B', 'D'])
        self.assertEqual(transit.shortest_path({**params, 'weight': 'distance_m'})['nodes'], ['A', 'D'])
        self.assertFalse(transit.shortest_path({**params, 'origin': 'D', 'destination': 'A'})['reachable'])

    def test_k_simple_paths_and_connectivity(self):
        g = graph([link('A', 'B', 1), link('B', 'D', 1), link('A', 'D', 4)])
        result = transit.k_shortest_path({'graph': g, 'origin': 'A', 'destination': 'D', 'k': 3})
        self.assertEqual([p['cost'] for p in result['paths']], [2, 4])
        stats = transit.network_analysis({'graph': g})
        self.assertEqual(stats['weak_components'], [['A', 'B', 'D'], ['C']])
        self.assertEqual(stats['strong_components'], [['A'], ['B'], ['C'], ['D']])

    def test_zero_length_route(self):
        g = graph([])
        self.assertEqual(transit.shortest_path({'graph': g, 'origin': 'A', 'destination': 'A'})['cost'], 0)
        self.assertEqual(transit.multimodal_routing({'graph': g, 'origin': 'A', 'destination': 'A', 'departure_seconds': 0})['travel_seconds'], 0)

    def test_missing_weight_unknown_node_and_negative_cost_rejected(self):
        for g, extra in [(graph([link('A', 'B', -1)]), {}), (graph([link('A', 'B', 1)]), {'weight': 'distance_m'}), (graph([]), {'destination': 'X'})]:
            with self.assertRaises(ValueError):
                transit.shortest_path({'graph': g, 'origin': 'A', 'destination': 'B', **extra})

    def test_graph_file_and_wrapped_gtfs_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'graph.json'
            path.write_text(json.dumps({'graph': graph([link('A', 'B', 10)])}), encoding='utf-8')
            result = transit.shortest_path({'graph_file': str(path), 'origin': 'A', 'destination': 'B'})
            self.assertEqual(result['cost'], 10)

    def test_wait_time_same_trip_and_transfer_minimum(self):
        g = graph([ride('A', 'B', 100, 200, 'T1'), ride('B', 'C', 210, 300, 'T1'),
                   ride('B', 'D', 210, 220, 'T2'), ride('B', 'D', 240, 270, 'T3')])
        params = {'graph': g, 'origin': 'A', 'departure_seconds': 90, 'transfer_min_seconds': 30}
        same = transit.multimodal_routing({**params, 'destination': 'C'})
        self.assertEqual((same['arrival_seconds'], same['transfers']), (300, 0))
        self.assertEqual(same['wait_seconds'], 20)
        changed = transit.multimodal_routing({**params, 'destination': 'D'})
        self.assertEqual((changed['arrival_seconds'], changed['transfers']), (270, 1))
        self.assertEqual(changed['travel_seconds'], 180)
        self.assertFalse(transit.multimodal_routing({**params, 'destination': 'D', 'max_transfers': 0})['reachable'])

    def test_earliest_stop_arrival_not_always_best_onboard_state(self):
        g = graph([ride('A', 'B', 10, 20, 'early'), ride('A', 'B', 12, 25, 'through'), ride('B', 'D', 26, 30, 'through')])
        route = transit.multimodal_routing({'graph': g, 'origin': 'A', 'destination': 'D', 'departure_seconds': 0, 'transfer_min_seconds': 10})
        self.assertTrue(route['reachable'])
        self.assertEqual(route['arrival_seconds'], 30)
        self.assertEqual(route['legs'][0]['trip_id'], 'through')

    def test_walking_counts_toward_transfer_time_and_modes_filter(self):
        g = graph([ride('A', 'B', 10, 20, 'T1'), link('B', 'C', 10), ride('C', 'D', 35, 45, 'T2')])
        args = {'graph': g, 'origin': 'A', 'destination': 'D', 'departure_seconds': 0, 'transfer_min_seconds': 15}
        self.assertEqual(transit.multimodal_routing(args)['arrival_seconds'], 45)
        self.assertFalse(transit.multimodal_routing({**args, 'modes': ['bus']})['reachable'])
        g['transfer_rules'] = [{'source': 'B', 'target': 'C', 'min_seconds': 20}]
        self.assertFalse(transit.multimodal_routing(args)['reachable'])

    def test_pickup_dropoff_and_prohibited_transfer(self):
        g = graph([ride('A', 'B', 10, 20, 'T1', drop_off_allowed=False), ride('B', 'C', 21, 30, 'T1', pickup_allowed=False), ride('B', 'D', 22, 25, 'T2')])
        args = {'graph': g, 'origin': 'A', 'departure_seconds': 0}
        self.assertTrue(transit.multimodal_routing({**args, 'destination': 'C'})['reachable'])
        self.assertFalse(transit.multimodal_routing({**args, 'destination': 'B'})['reachable'])
        self.assertFalse(transit.multimodal_routing({**args, 'destination': 'D'})['reachable'])
        self.assertFalse(transit.multimodal_routing({**args, 'origin': 'B', 'destination': 'C'})['reachable'])
        g['edges'][0]['drop_off_allowed'] = True
        g['transfer_rules'] = [{'source': 'B', 'target': 'B', 'prohibited': True}]
        self.assertFalse(transit.multimodal_routing({**args, 'destination': 'D'})['reachable'])

    def test_no_automatic_midnight_rollover(self):
        g = graph([ride('A', 'B', 86410, 86500, 'night')])
        args = {'graph': g, 'origin': 'A', 'destination': 'B'}
        self.assertEqual(transit.multimodal_routing({**args, 'departure_seconds': 86400})['travel_seconds'], 100)
        self.assertFalse(transit.multimodal_routing({**args, 'departure_seconds': 86420})['reachable'])

    def test_od_and_cumulative_opportunities(self):
        g = graph([link('A', 'B', 10), link('B', 'C', 10)])
        args = {'graph': g, 'departure_seconds': 0}
        matrix = transit.od_analysis({**args, 'origins': ['A', 'C'], 'destinations': ['B', 'D']})
        self.assertEqual(matrix['pair_count'], 4)
        self.assertEqual([r['travel_seconds'] for r in matrix['rows']], [10, None, None, None])
        access = transit.accessibility({**args, 'origin': 'A', 'budget_seconds': 15, 'destinations': ['B', 'C', 'D'], 'opportunities': {'B': 4, 'C': 10, 'D': 50}})
        self.assertEqual(access['reachable_destinations'], ['B'])
        self.assertEqual(access['reachable_opportunities'], 4)


class GTFSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'gtfs.zip'
        self.tables = {
            'stops.txt': 'stop_id,stop_name,stop_lat,stop_lon\nA,First,30,114\nB,Second,30.1,114.1\n',
            'routes.txt': 'route_id,route_type\nR,3\n',
            'trips.txt': 'route_id,service_id,trip_id\nR,WEEK,T1\nR,ADDED,T2\n',
            'stop_times.txt': 'trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,24:10:00,24:10:00,A,1\nT1,24:20:00,24:20:00,B,2\nT2,08:00:00,08:00:00,A,1\nT2,08:10:00,08:10:00,B,2\n',
            'calendar.txt': 'service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nWEEK,1,1,1,1,1,0,0,20260101,20261231\n',
            'calendar_dates.txt': 'service_id,date,exception_type\nWEEK,20261111,2\nADDED,20261111,1\n',
        }

    def tearDown(self):
        self.temp.cleanup()

    def read(self, service_date='2026-11-10'):
        with zipfile.ZipFile(self.path, 'w') as z:
            for name, content in self.tables.items():
                z.writestr(name, content)
        return transit.gtfs_reader({'file': str(self.path), 'service_date': service_date})

    def test_calendar_exceptions_and_extended_hours(self):
        regular = self.read()
        self.assertEqual(regular['active_service_ids'], ['WEEK'])
        self.assertEqual(regular['graph']['edges'][0]['departure_seconds'], 87000)
        exceptional = self.read('2026-11-11')
        self.assertEqual(exceptional['active_service_ids'], ['ADDED'])
        self.assertEqual(exceptional['graph']['edges'][0]['trip_id'], 'T2')
        self.assertEqual(self.read('2026-11-14')['trip_count'], 0)

    def test_calendar_dates_only(self):
        del self.tables['calendar.txt']
        self.assertEqual(self.read('2026-11-11')['trip_count'], 1)

    def test_missing_service_calendar_rejected(self):
        del self.tables['calendar.txt']
        del self.tables['calendar_dates.txt']
        with self.assertRaisesRegex(ValueError, 'calendar'):
            self.read()

    def test_no_fabricated_frequency_departures(self):
        self.tables['frequencies.txt'] = 'trip_id,start_time,end_time,headway_secs\nT1,08:00:00,09:00:00,600\n'
        with self.assertRaisesRegex(ValueError, 'Frequency'):
            self.read()

    def test_missing_and_reversed_times_rejected(self):
        original = self.tables['stop_times.txt']
        for replacement in ['', '23:59:00']:
            self.tables['stop_times.txt'] = original.replace('24:20:00', replacement)
            with self.assertRaises(ValueError):
                self.read()

    def test_gtfs_graph_routes_after_midnight(self):
        data = self.read()
        result = transit.multimodal_routing({'graph': data['graph'], 'origin': 'A', 'destination': 'B', 'departure_seconds': 86900})
        self.assertEqual(result['travel_seconds'], 700)
        self.assertEqual(result['legs'][0]['mode'], 'bus')

    def test_gtfs_min_transfer_requires_explicit_duration(self):
        self.tables['transfers.txt'] = 'from_stop_id,to_stop_id,transfer_type\nA,B,2\n'
        with self.assertRaisesRegex(ValueError, 'min_transfer_time'):
            self.read()

    def test_duplicate_trip_id_rejected(self):
        self.tables['trips.txt'] += 'R,WEEK,T1\n'
        with self.assertRaisesRegex(ValueError, 'Duplicate GTFS trip_id'):
            self.read()


if __name__ == '__main__':
    unittest.main()
