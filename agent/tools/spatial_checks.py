"""确定性空间检查：核对输入记录、距离下界和GeoJSON，不替模型选择分析方法。"""
import csv
import json
import math
from pyproj import Geod, Transformer
from shapely.geometry import shape
from shapely.validation import explain_validity
from .planning import local_file

SCOPE = '检查坐标解析、同一对原始点的距离下界及几何结构；不证明站位准确、路径可通行或结论适用于全部居民。'
GEOD = Geod(ellps='WGS84')


def lonlat(x, y, crs):
    if not crs:
        raise ValueError('缺少坐标系；请读取来源中的坐标系声明')
    x, y = float(x), float(y)
    if not all(math.isfinite(v) for v in (x, y)):
        raise ValueError('坐标不是有限数值')
    lon, lat = Transformer.from_crs(crs, 4326, always_xy=True).transform(x, y, errcheck=True)
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 < lat < 90):
        raise ValueError('坐标无法解释为有效经纬度；核对坐标系、单位和列顺序')
    return lon, lat


def origin(folder, spec):
    value = json.loads(local_file(folder, spec['文件']).read_text(encoding='utf-8-sig'))
    for key in spec.get('路径', []):
        value = value[key]
    return lonlat(value[spec['经度字段']], value[spec['纬度字段']], spec['坐标系'])


def check_distances(folder, spec):
    start = origin(folder, spec['起点记录'])
    factor = {'米': 1.0, '千米': 1000.0, '英尺': 0.3048}.get(spec['距离单位'])
    if factor is None:
        raise ValueError('距离单位需为米、千米或英尺')
    problems, count, failures = [], 0, 0
    # 每张表只构建一次坐标变换，行号含CSV表头。
    crs = spec['终点坐标系']
    converter = Transformer.from_crs(crs, 4326, always_xy=True)
    with local_file(folder, spec['文件']).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        columns = [spec[k] for k in ['终点经度列', '终点纬度列', '距离列']]
        if not reader.fieldnames or any(c not in reader.fieldnames for c in columns):
            raise ValueError('指定列不在CSV表头中：' + ', '.join(columns))
        for line, row in enumerate(reader, 2):
            count += 1
            issue = None
            try:
                x, y, reported = (float(row[c]) for c in columns)
                if not all(math.isfinite(v) for v in (x, y, reported)):
                    raise ValueError('缺失或非有限数值；不能当作零距离')
                lon, lat = converter.transform(x, y, errcheck=True)
                if not (-180 <= lon <= 180 and -90 < lat < 90):
                    raise ValueError('终点坐标越界；核对坐标系、单位和列顺序')
                metres = reported * factor
                if not math.isfinite(metres): raise ValueError('单位转换后的距离不是有限数值')
                if metres < 0:
                    raise ValueError('距离为负数')
                direct = GEOD.inv(*start, lon, lat)[2]
                if metres + 1.0 < direct:
                    issue = {'行号': line, '报告距离米': round(metres, 3), '直线下界米': round(direct, 3),
                             '原因': '完整路径短于同一起终点的直线距离（容差1米）',
                             '核查方向': '核对是否遗漏原始点到网络的接入段、是否将两个原始点替换成同一节点，以及距离单位'}
            except (ValueError, TypeError, OverflowError) as exc:
                issue = {'行号': line, '原因': str(exc)}
            if issue:
                failures += 1
                if len(problems) < 10: problems.append(issue)
    if not count:
        failures += 1; problems.append({'原因': '距离表没有数据行'})
    return {'类型': '距离下界', '文件': spec['文件'], '起点来源': spec['起点记录'],
            '起点经纬度': start, '条数': count, '失败数': failures, '问题': problems}


def check_geojson(folder, name):
    data = json.loads(local_file(folder, name).read_text(encoding='utf-8-sig'))
    if data.get('type') != 'FeatureCollection' or data.get('crs'):
        raise ValueError('图层需为WGS84 FeatureCollection；投影坐标请先转换，不能仅删除crs字段')
    features = data.get('features')
    if not isinstance(features, list) or not features:
        raise ValueError('图层没有要素')
    problems, failures = [], 0

    def coordinates(g):
        if not isinstance(g, dict): raise ValueError('几何为空')
        if g.get('type') == 'GeometryCollection':
            for child in g.get('geometries', []): coordinates(child)
            return
        def walk(v):
            if not isinstance(v, (list, tuple)) or not v: raise ValueError('坐标为空或结构无效')
            if isinstance(v[0], (int, float)):
                if len(v) < 2 or not all(isinstance(n,(int,float)) and math.isfinite(n) for n in v):
                    raise ValueError('坐标缺失或含非有限数值')
                if not (-180 <= v[0] <= 180 and -90 < v[1] < 90):
                    raise ValueError('经纬度越界；核对原始坐标系并实际转换')
            else:
                for child in v: walk(child)
        walk(g.get('coordinates'))

    for i, feature in enumerate(features, 1):
        try:
            geometry = feature.get('geometry')
            coordinates(geometry)
            if geometry.get('type') == 'LineString' and len(geometry['coordinates']) < 2:
                raise ValueError('LineString至少需要两个坐标；单节点不是一条有效路径')
            g = shape(geometry)
            if g.is_empty or not g.is_valid:
                raise ValueError('无效或空几何：' + explain_validity(g))
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            failures += 1
            if len(problems) < 10: problems.append({'要素序号': i, '原因': str(exc)})
    return {'类型': '图层几何', '文件': name, '条数': len(features), '失败数': failures, '问题': problems}


def check_spatial(folder, spec):
    if not isinstance(spec, dict):
        return {'状态': '失败', '范围': SCOPE, '结果': [{'失败数': 1, '问题': [{'原因': '空间检查配置需为对象'}]}]}
    results=[]
    for kind, items in [('距离表', spec.get('距离表', [])), ('图层', spec.get('图层', []))]:
        if not isinstance(items, list):
            results.append({'类型': kind, '失败数': 1, '问题': [{'原因': '检查项目需为列表'}]}); continue
        for item in items:
            try:
                results.append(check_distances(folder, item) if kind=='距离表' else check_geojson(folder, item))
            except Exception as exc:
                results.append({'类型': kind, '文件': item.get('文件') if isinstance(item,dict) else item,
                                '失败数': 1, '问题': [{'原因': type(exc).__name__ + ': ' + str(exc)}]})
    status = '未检查' if not results else ('失败' if any(r['失败数'] for r in results) else '通过')
    return {'状态': status, '范围': SCOPE, '结果': results}


def submission_check(folder, action, previous_spec=None):
    """重新读取当前成果，避免复用文件改写前的检查结果。声明的GeoJSON自动检查。"""
    spec = action.get('空间检查', previous_spec or {})
    if not isinstance(spec, dict): return check_spatial(folder, spec), spec
    spec = dict(spec)
    if not isinstance(spec.get('图层', []), list): return check_spatial(folder, spec), spec
    layers = list(spec.get('图层', []))
    for item in action.get('成果', []):
        if isinstance(item, dict) and isinstance(item.get('文件'),str) and item['文件'].lower().endswith('.geojson'):
            if item['文件'] not in layers: layers.append(item['文件'])
    spec['图层'] = layers
    return check_spatial(folder, spec), spec
