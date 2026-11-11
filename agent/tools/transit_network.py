"""Offline transportation tools over an explicit directed graph.

Graph contract: nodes=[{id,...}], edges=[{source,target,mode,time_seconds,...}].
Scheduled edges additionally carry departure_seconds, arrival_seconds, trip_id.
Times are seconds since the selected service day's start, including values >86400.
Static shortest-path tools compare supplied weights, not timetable feasibility.
GTFS semantics: https://gtfs.org/documentation/schedule/reference/
"""
import csv
from datetime import date
import heapq
import io
import itertools
import json
import math
from pathlib import Path
import zipfile

import networkx as nx


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be a finite nonnegative number')
    return value


def _integer(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f'{name} must be an integer from {minimum}' + (f' to {maximum}' if maximum is not None else ''))
    return value


def _seconds(value):
    try:
        hour, minute, second = (int(x) for x in value.split(':'))
    except (ValueError, AttributeError):
        raise ValueError(f'Invalid GTFS time: {value!r}') from None
    if hour < 0 or not 0 <= minute < 60 or not 0 <= second < 60:
        raise ValueError(f'Invalid GTFS time: {value!r}')
    return hour * 3600 + minute * 60 + second


def _read_graph(params):
    if ('graph' in params) == ('graph_file' in params):
        raise ValueError('Supply exactly one of graph or graph_file')
    graph = params.get('graph')
    if graph is None:
        graph = json.loads(Path(params['graph_file']).read_text(encoding='utf-8-sig'))
        if 'graph' in graph and 'nodes' not in graph:
            graph = graph['graph']
    if not isinstance(graph, dict) or graph.get('directed', True) is not True:
        raise ValueError('A directed graph is required; declare both directions explicitly')
    nodes = graph.get('nodes')
    edges = graph.get('edges')
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError('graph needs nodes and edges lists')
    ids = [n.get('id') for n in nodes if isinstance(n, dict)]
    if len(ids) != len(nodes) or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
        raise ValueError('Node ids must be unique nonempty strings')
    node_set = set(ids)
    for edge in edges:
        if not isinstance(edge, dict) or edge.get('source') not in node_set or edge.get('target') not in node_set:
            raise ValueError('Every edge must refer to declared source and target nodes')
        if not isinstance(edge.get('mode'), str) or not edge['mode']:
            raise ValueError('Every edge must declare mode')
        _number(edge.get('time_seconds'), 'time_seconds')
        if 'distance_m' in edge:
            _number(edge['distance_m'], 'distance_m')
        for flag in ('pickup_allowed', 'drop_off_allowed'):
            if flag in edge and not isinstance(edge[flag], bool):
                raise ValueError(f'{flag} must be boolean')
        if ('departure_seconds' in edge) != ('arrival_seconds' in edge):
            raise ValueError('Scheduled edges need both departure_seconds and arrival_seconds')
        if 'departure_seconds' in edge:
            departure = _number(edge['departure_seconds'], 'departure_seconds')
            arrival = _number(edge['arrival_seconds'], 'arrival_seconds')
            if arrival < departure or abs(arrival - departure - edge['time_seconds']) > 1e-6:
                raise ValueError('Scheduled arrival and duration are inconsistent')
            if not isinstance(edge.get('trip_id'), str) or not edge['trip_id']:
                raise ValueError('Scheduled edges need trip_id')
    return graph


def _modes(params):
    modes = params.get('modes')
    if modes is not None and (not isinstance(modes, list) or not modes or any(not isinstance(x, str) for x in modes)):
        raise ValueError('modes must be a nonempty list of mode names')
    return set(modes) if modes else None


def gtfs_reader(params):
    """Read a GTFS ZIP for service_date (YYYY-MM-DD), yielding a scheduled graph.

    Supports explicit stop times, calendar exceptions, ordinary pickup/drop-off
    restrictions, and stop-to-stop minimum/prohibited transfer rules. Frequency,
    on-demand and trip-specific transfer feeds require a separate adapter.
    No pedestrian links or travel times are inferred from coordinates.
    """
    service_date = date.fromisoformat(params['service_date'])
    service_text = service_date.strftime('%Y%m%d')
    with zipfile.ZipFile(params['file']) as archive:
        def rows(name, required=False):
            if name not in archive.namelist():
                if required:
                    raise ValueError(f'GTFS ZIP lacks {name}')
                return []
            with archive.open(name) as stream:
                return list(csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig', newline='')))
        stops, routes, trips = rows('stops.txt', True), rows('routes.txt', True), rows('trips.txt', True)
        times = rows('stop_times.txt', True)
        calendar, exceptions = rows('calendar.txt'), rows('calendar_dates.txt')
        frequencies, transfers = rows('frequencies.txt'), rows('transfers.txt')
    if not calendar and not exceptions:
        raise ValueError('GTFS requires calendar.txt or calendar_dates.txt')
    weekdays = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
    active = {r['service_id'] for r in calendar
              if r['start_date'] <= service_text <= r['end_date'] and r[weekdays[service_date.weekday()]] == '1'}
    for row in exceptions:
        if row['date'] == service_text:
            if row['exception_type'] == '1':
                active.add(row['service_id'])
            elif row['exception_type'] == '2':
                active.discard(row['service_id'])
            else:
                raise ValueError('Invalid GTFS exception_type')
    if len({t['trip_id'] for t in trips}) != len(trips):
        raise ValueError('Duplicate GTFS trip_id')
    if len({r['route_id'] for r in routes}) != len(routes):
        raise ValueError('Duplicate GTFS route_id')
    selected = {t['trip_id']: t for t in trips if t['service_id'] in active}
    if any(r['trip_id'] in selected for r in frequencies):
        raise ValueError('Frequency-based trips need an explicit frequency adapter; no departures were invented')
    routes_by_id = {r['route_id']: r for r in routes}
    stop_ids = {s['stop_id'] for s in stops}
    if len(stop_ids) != len(stops):
        raise ValueError('Duplicate GTFS stop_id')
    grouped = {}
    for row in times:
        if row['trip_id'] in selected:
            if row.get('stop_id') not in stop_ids:
                raise ValueError('GTFS stop_times refers to unknown stop')
            grouped.setdefault(row['trip_id'], []).append(row)
    mode_names = {'0': 'tram', '1': 'subway', '2': 'rail', '3': 'bus', '4': 'ferry', '5': 'cable_tram', '6': 'aerial_lift', '7': 'funicular', '11': 'trolleybus', '12': 'monorail'}
    edges = []
    for trip_id, trip in selected.items():
        seq = sorted(grouped.get(trip_id, []), key=lambda x: int(x['stop_sequence']))
        if len(seq) < 2 or len({int(x['stop_sequence']) for x in seq}) != len(seq):
            raise ValueError(f'Trip {trip_id} needs distinct ordered stop times')
        route = routes_by_id[trip['route_id']]
        route_type = route['route_type']
        mode = mode_names.get(route_type, 'gtfs_route_type_' + route_type)
        parsed = []
        for row in seq:
            arrival, departure = _seconds(row.get('arrival_time')), _seconds(row.get('departure_time'))
            if departure < arrival:
                raise ValueError('GTFS departure precedes arrival at a stop')
            pickup, drop = row.get('pickup_type', '') or '0', row.get('drop_off_type', '') or '0'
            if pickup not in {'0', '1'} or drop not in {'0', '1'}:
                raise ValueError('On-demand pickup/drop-off requires a separate adapter')
            parsed.append((row, arrival, departure, pickup == '0', drop == '0'))
        for first, second in zip(parsed, parsed[1:]):
            a, _, departure, pickup, _ = first
            b, arrival, _, _, drop = second
            if arrival < departure:
                raise ValueError('GTFS trip times are not chronological')
            edges.append({'source': a['stop_id'], 'target': b['stop_id'], 'mode': mode,
                          'time_seconds': arrival - departure, 'departure_seconds': departure,
                          'arrival_seconds': arrival, 'trip_id': trip_id, 'route_id': trip['route_id'],
                          'pickup_allowed': pickup, 'drop_off_allowed': drop})
    transfer_rules = []
    parent_stations = {s.get('parent_station') for s in stops if s.get('parent_station')}
    for row in transfers:
        if any(row.get(k) for k in ('from_trip_id', 'to_trip_id', 'from_route_id', 'to_route_id')):
            raise ValueError('Trip/route-specific transfers require a separate adapter')
        kind = row.get('transfer_type', '0') or '0'
        if kind not in {'0', '2', '3'}:
            raise ValueError('Timed/in-seat GTFS transfers require a separate adapter')
        if row['from_stop_id'] not in stop_ids or row['to_stop_id'] not in stop_ids:
            raise ValueError('GTFS transfer refers to an unknown stop')
        if row['from_stop_id'] in parent_stations or row['to_stop_id'] in parent_stations:
            raise ValueError('Station-level transfer inheritance requires a separate adapter')
        if kind == '2' and not row.get('min_transfer_time'):
            raise ValueError('GTFS transfer_type 2 requires min_transfer_time')
        transfer_rules.append({'source': row['from_stop_id'], 'target': row['to_stop_id'],
                               'prohibited': kind == '3',
                               'min_seconds': _number(int(row.get('min_transfer_time') or 0), 'min_transfer_time')})
    nodes = []
    for stop in stops:
        node = {'id': stop['stop_id'], 'name': stop.get('stop_name', '')}
        if stop.get('stop_lon') and stop.get('stop_lat'):
            node.update(lon=float(stop['stop_lon']), lat=float(stop['stop_lat']))
        nodes.append(node)
    graph = {'directed': True, 'nodes': nodes, 'edges': edges, 'transfer_rules': transfer_rules,
             'service_date': service_date.isoformat(), 'time_basis': 'seconds_since_service_day_start'}
    return {'graph': graph, 'active_service_ids': sorted(active), 'trip_count': len(selected),
            'stop_count': len(nodes), 'edge_count': len(edges)}


def _static_graph(graph, params):
    weight = params.get('weight', 'time_seconds')
    if weight not in {'time_seconds', 'distance_m'}:
        raise ValueError('weight must be time_seconds or distance_m')
    modes = _modes(params)
    g = nx.DiGraph()
    g.add_nodes_from(n['id'] for n in graph['nodes'])
    for index, edge in enumerate(graph['edges']):
        if modes and edge['mode'] not in modes:
            continue
        cost = _number(edge.get(weight), weight)
        a, b = edge['source'], edge['target']
        # For a static node-path comparison, retain the cheapest parallel edge.
        if not g.has_edge(a, b) or cost < g[a][b]['cost']:
            g.add_edge(a, b, cost=cost, edge_index=index)
    return g, weight


def _endpoints(g, params):
    origin, destination = params['origin'], params['destination']
    if origin not in g or destination not in g:
        raise ValueError('origin and destination must be graph node ids')
    return origin, destination


def _static_result(graph, g, path, weight):
    indices = [g[a][b]['edge_index'] for a, b in zip(path, path[1:])]
    return {'reachable': True, 'nodes': path, 'edge_indices': indices,
            'cost': sum(graph['edges'][i][weight] for i in indices), 'weight': weight,
            'routing_basis': 'static_edge_weights'}


def shortest_path(params):
    """Static directed weighted path; args: graph[_file], origin, destination, weight?, modes?."""
    graph = _read_graph(params)
    g, weight = _static_graph(graph, params)
    a, b = _endpoints(g, params)
    try:
        return _static_result(graph, g, nx.shortest_path(g, a, b, weight='cost'), weight)
    except nx.NetworkXNoPath:
        return {'reachable': False, 'nodes': [], 'cost': None, 'weight': weight, 'routing_basis': 'static_edge_weights'}


def k_shortest_path(params):
    """Up to k distinct simple node paths, ordered by static weight; k defaults to 3 (max 20)."""
    graph = _read_graph(params)
    g, weight = _static_graph(graph, params)
    a, b = _endpoints(g, params)
    k = _integer(params.get('k', 3), 'k', 1, 20)
    try:
        paths = list(itertools.islice(nx.shortest_simple_paths(g, a, b, weight='cost'), k))
    except nx.NetworkXNoPath:
        paths = []
    return {'paths': [_static_result(graph, g, p, weight) for p in paths], 'count': len(paths)}


def network_analysis(params):
    """Directed connectivity, degrees, and weak/strong components; modes may filter edges."""
    graph = _read_graph(params)
    modes = _modes(params)
    g = nx.MultiDiGraph()
    g.add_nodes_from(n['id'] for n in graph['nodes'])
    g.add_edges_from((e['source'], e['target']) for e in graph['edges'] if not modes or e['mode'] in modes)
    return {'directed': True, 'node_count': g.number_of_nodes(), 'edge_count': g.number_of_edges(),
            'weak_components': sorted((sorted(c) for c in nx.weakly_connected_components(g)), key=lambda c: c[0]),
            'strong_components': sorted((sorted(c) for c in nx.strongly_connected_components(g)), key=lambda c: c[0]),
            'degrees': [{'node': n, 'in_degree': g.in_degree(n), 'out_degree': g.out_degree(n)} for n in sorted(g)]}


def _timed_route(graph, params):
    nodes = {n['id'] for n in graph['nodes']}
    origin, destination = _endpoints(nodes, params)
    departure = _number(params.get('departure_seconds'), 'departure_seconds')
    transfer_min = _number(params.get('transfer_min_seconds', 0), 'transfer_min_seconds')
    max_transfers = _integer(params.get('max_transfers', 4), 'max_transfers', 0, 20)
    modes = _modes(params)
    adjacency = {n: [] for n in nodes}
    for index, edge in enumerate(graph['edges']):
        if not modes or edge['mode'] in modes:
            adjacency[edge['source']].append((index, edge))
    rules = graph.get('transfer_rules', [])
    for rule in rules:
        if rule.get('source') not in nodes or rule.get('target') not in nodes:
            raise ValueError('Transfer rule refers to an unknown stop')
        _number(rule.get('min_seconds', 0), 'transfer min_seconds')
        if 'prohibited' in rule and not isinstance(rule['prohibited'], bool):
            raise ValueError('transfer prohibited must be boolean')
    # State retains onboard trip and last alighting point/time. This prevents
    # earliest-arrival pruning from discarding a later but transfer-feasible trip.
    # (node, onboard_trip, last_trip, alight_stop, alight_time, can_alight, boardings)
    start = (origin, None, None, None, None, True, 0)
    best = {start: departure}
    parent = {}
    serial = itertools.count()
    queue = [(departure, next(serial), start)]
    goal = None
    while queue:
        at, _, state = heapq.heappop(queue)
        if best.get(state) != at:
            continue
        node, onboard, last_trip, alight_stop, alight_time, can_alight, boardings = state
        if node == destination and can_alight:
            goal = state
            break
        for index, edge in adjacency[node]:
            scheduled = 'departure_seconds' in edge
            next_boardings = boardings
            next_onboard, next_last = onboard, last_trip
            next_stop, next_alight = alight_stop, alight_time
            if scheduled:
                trip = edge['trip_id']
                staying = onboard == trip
                earliest = at
                if not staying:
                    if not can_alight or edge.get('pickup_allowed', True) is not True:
                        continue
                    next_boardings += 1
                    if next_boardings > max_transfers + 1:
                        continue
                    if last_trip is not None:
                        stop = node if onboard is not None else alight_stop
                        alighted = at if onboard is not None else alight_time
                        matching = [r for r in rules if r['source'] == stop and r['target'] == node]
                        if any(r.get('prohibited') for r in matching):
                            continue
                        minimum = max([transfer_min] + [r.get('min_seconds', 0) for r in matching])
                        earliest = max(at, alighted + minimum)
                leave, arrive = edge['departure_seconds'], edge['arrival_seconds']
                if leave < earliest:
                    continue
                next_onboard = next_last = trip
                next_stop = next_alight = None
                next_can_alight = edge.get('drop_off_allowed', True) is True
            else:
                if not can_alight:
                    continue
                leave, arrive = at, at + edge['time_seconds']
                if onboard is not None:
                    next_stop, next_alight = node, at
                next_onboard = None
                next_can_alight = True
            nxt = (edge['target'], next_onboard, next_last, next_stop, next_alight, next_can_alight, next_boardings)
            if arrive < best.get(nxt, math.inf):
                best[nxt] = arrive
                parent[nxt] = (state, index, leave, arrive)
                heapq.heappush(queue, (arrive, next(serial), nxt))
    if goal is None:
        return {'reachable': False, 'nodes': [], 'legs': [], 'arrival_seconds': None,
                'travel_seconds': None, 'departure_seconds': departure}
    legs = []
    current = goal
    while current != start:
        previous, index, leave, arrive = parent[current]
        edge = graph['edges'][index]
        legs.append({'edge_index': index, 'source': edge['source'], 'target': edge['target'],
                     'mode': edge['mode'], 'trip_id': edge.get('trip_id'), 'departure_seconds': leave,
                     'arrival_seconds': arrive, 'wait_seconds': leave - best[previous]})
        current = previous
    legs.reverse()
    arrival = best[goal]
    return {'reachable': True, 'nodes': [origin] + [leg['target'] for leg in legs], 'legs': legs,
            'departure_seconds': departure, 'arrival_seconds': arrival, 'travel_seconds': arrival - departure,
            'wait_seconds': sum(leg['wait_seconds'] for leg in legs), 'transfers': max(0, goal[-1] - 1)}


def multimodal_routing(params):
    """Earliest arrival with schedule/wait/transfer constraints and explicit walking edges.

    Args: graph[_file], origin, destination, departure_seconds, modes?,
    transfer_min_seconds? (default 0), max_transfers? (default 4).
    No unsupplied walking link, capacity, or congestion adjustment is invented.
    """
    return _timed_route(_read_graph(params), params)


def od_analysis(params):
    """Earliest-arrival OD table: origins/destinations lists plus timed routing args."""
    graph = _read_graph(params)
    origins, destinations = params['origins'], params['destinations']
    if not isinstance(origins, list) or not isinstance(destinations, list) or not origins or not destinations:
        raise ValueError('origins and destinations must be nonempty lists')
    if len(origins) * len(destinations) > 10000:
        raise ValueError('OD table is limited to 10000 pairs per call')
    rows = []
    for a in origins:
        for b in destinations:
            route = _timed_route(graph, {**params, 'origin': a, 'destination': b})
            rows.append({'origin': a, 'destination': b, 'reachable': route['reachable'],
                         'travel_seconds': route['travel_seconds'], 'arrival_seconds': route['arrival_seconds']})
    return {'rows': rows, 'pair_count': len(rows)}


def accessibility(params):
    """Count listed destinations reachable within budget_seconds from origin at departure_seconds.

    Optional opportunities maps destination ids to nonnegative opportunity counts.
    The measure is cumulative opportunity accessibility, not an inferred population model.
    """
    graph = _read_graph(params)
    budget = _number(params.get('budget_seconds'), 'budget_seconds')
    destinations = params.get('destinations', [n['id'] for n in graph['nodes'] if n['id'] != params['origin']])
    if not isinstance(destinations, list) or len(set(destinations)) != len(destinations):
        raise ValueError('destinations must be a list of distinct node ids')
    opportunities = params.get('opportunities')
    if opportunities is not None:
        if not isinstance(opportunities, dict) or any(d not in opportunities for d in destinations):
            raise ValueError('opportunities must provide a value for every destination')
        for d in destinations:
            _number(opportunities[d], 'opportunity count')
    rows = []
    for target in destinations:
        result = _timed_route(graph, {**params, 'destination': target})
        rows.append({'destination': target, 'travel_seconds': result['travel_seconds'],
                     'within_budget': result['reachable'] and result['travel_seconds'] <= budget})
    reachable = [r['destination'] for r in rows if r['within_budget']]
    return {'rows': rows, 'budget_seconds': budget, 'reachable_destinations': reachable,
            'reachable_count': len(reachable),
            'reachable_opportunities': sum(opportunities[d] for d in reachable) if opportunities is not None else None}


TOOLS = {'GTFS Reader': gtfs_reader, 'Shortest Path': shortest_path, 'K-shortest Path': k_shortest_path,
         'Network Analysis': network_analysis, 'Multimodal Routing': multimodal_routing,
         'OD Analysis': od_analysis, 'Accessibility': accessibility}
FILE_PARAMETERS = {name: ('file',) if name == 'GTFS Reader' else ('graph_file',) for name in TOOLS}
