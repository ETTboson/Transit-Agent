"""The public action contract presented to the planner."""
TOOL_HELP = {
    'GTFS Reader': {'file': 'GTFS ZIP', 'service_date': 'YYYY-MM-DD'},
    'Geocoding': {'file': 'WGS84 GeoJSON gazetteer', 'query': 'exact name or address'},
    'Spatial Search': {'file': 'WGS84 GeoJSON', 'center': '[longitude, latitude]', 'radius_m': 'number', 'projected_crs': 'local projected CRS in metres'},
    'Buffer': {'file': 'WGS84 GeoJSON', 'radius_m': 'number', 'projected_crs': 'local projected CRS in metres'},
    'Overlay': {'file': 'WGS84 GeoJSON', 'other_file': 'WGS84 GeoJSON', 'projected_crs': 'local projected CRS in metres', 'operation': 'intersection'},
    'Shortest Path': {'graph_file': 'graph JSON (or inline graph)', 'origin': 'node ID', 'destination': 'node ID', 'weight': 'time_seconds or distance_m'},
    'K-shortest Path': {'graph_file': 'graph JSON (or inline graph)', 'origin': 'node ID', 'destination': 'node ID', 'k': 'positive integer', 'weight': 'time_seconds or distance_m'},
    'Network Analysis': {'graph_file': 'graph JSON (or inline graph)'},
    'Multimodal Routing': {'graph_file': 'graph JSON (or inline graph)', 'origin': 'node ID', 'destination': 'node ID', 'departure_seconds': 'seconds from service-day midnight', 'modes': 'allowed mode list', 'transfer_min_seconds': 'minimum transfer time'},
    'OD Analysis': {'graph_file': 'graph JSON (or inline graph)', 'origins': 'node ID list', 'destinations': 'node ID list', 'departure_seconds': 'seconds from service-day midnight'},
    'Accessibility': {'graph_file': 'graph JSON (or inline graph)', 'origin': 'node ID', 'departure_seconds': 'seconds from service-day midnight', 'budget_seconds': 'maximum journey time'},
}

ACTION_PROMPT = '''
Professional tools perform calculations through deterministic code. Use this action structure:
{"action":"professional_tool","task":"route_a","tool":"Shortest Path","params":{"graph_file":"network.json","origin":"A","destination":"B","weight":"time_seconds"},"file_dependencies":[],"reason":"Explain how the method addresses the question"}
Choose task IDs that start with an English letter and contain only letters, digits, underscores or hyphens, up to 64 characters. Reuse the same ID for the same analysis step; changing its parameters updates that node. Use different IDs for separate analysis branches.
To use upstream outputs, first run GTFS Reader as task feed, then set the graph parameter to {"result":"feed","path":["graph"]}. The program resolves the actual output and records the dependency. References must identify real results and existing field paths. Supply exactly one of graph or graph_file.
When data change or a session continues, call the downstream task you need. The program checks input versions and parameters along the reference chain, recomputes affected nodes and reuses valid results. You do not need to rerun every step. Use parameters from the current question and materials. List guides or rule files that influence parameter choices in file_dependencies. Explicitly update the corresponding node parameters when analysis conditions change.
File paths must point into the current data or working directory. Outputs are saved as tool_results/<task_id>.json. Professional tools and code execution share a budget of 10 computations. A single call can recompute several dependency nodes; each node actually executed counts, while cache reuse does not. The program manages professional-tool results and tool_graph.json; do not overwrite them through code execution.
Geocoding performs exact matches in the supplied gazetteer rather than guessing locations online. Static shortest paths do not calculate timetable waiting; use Multimodal Routing when departures or transfers matter. Do not invent missing edges, trips, transfer connections or capacity data. Represent peak-period differences through input data for the corresponding period.
'''
