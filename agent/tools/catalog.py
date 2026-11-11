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
专业工具通过确定性代码执行真实计算。调用结构：
{"动作":"专业工具","任务":"route_a","工具":"Shortest Path","参数":{"graph_file":"network.json","origin":"A","destination":"B","weight":"time_seconds"},"资料依赖":[],"理由":"说明方法与问题的对应"}。
任务编号由你命名（英文字母开头，字母、数字、下划线或连字符，最长64字符）。相同分析步骤继续使用同一编号，修改其参数会更新该节点。不同分析分支使用不同编号。
使用上游输出：先以任务feed执行GTFS Reader，随后参数graph可填{"结果":"feed","路径":["graph"]}，程序解析真实结果并记录依赖。返回的结果引用不是自由编造的答案；字段路径必须存在。graph与graph_file二选一。
更新资料或继续会话时，请调用需要的下游任务；程序沿引用链核验输入版本与参数，只重算变化影响的节点，其余结果复用。不必逐个重跑全部步骤。参数以当前问题和资料为准；影响参数选择的导则、规则文件请列入资料依赖。更改分析条件应显式更新相应节点参数。
文件路径指向本次资料目录或工作目录，输出为tool_results/任务编号.json。专业工具与运行代码共享10次计算预算；一次调用可能重算多个依赖节点，每个实际执行的节点计数，缓存复用不计计算次数。专业工具结果和tool_graph.json由程序管理，不用运行代码覆盖。
Geocoding在提供的地名表中精确匹配，不在线猜位置。静态最短路不处理时刻表候车，涉及发车/换乘时选择Multimodal Routing。缺少边、班次、换乘连接或容量资料时不可补造；峰时差异通过对应时段的输入数据表达。
'''
