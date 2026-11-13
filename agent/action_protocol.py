"""Normalize the English model protocol without rewriting data or legacy traces."""


ACTION_NAMES = {
    'run_code': '运行代码',
    'submit': '提交',
    'professional_tool': '专业工具',
    'search_official': '检索官方资料',
    'fetch_official': '获取官方资料',
    'draw_map': '绘制地图',
    'check_spatial': '检查空间结果',
}
COMMON_KEYS = {'action': '动作', 'assessment': '当前判断', 'reason': '理由'}
ACTION_KEYS = {
    '运行代码': {'code': '代码'},
    '提交': {'conclusion': '结论', 'evidence': '依据', 'unresolved': '待解决',
           'artifacts': '成果', 'spatial_check': '空间检查'},
    '专业工具': {'task': '任务', 'tool': '工具', 'params': '参数', 'file_dependencies': '资料依赖'},
    '检索官方资料': {'query': '检索词'},
    '获取官方资料': {'url': '地址'},
    '绘制地图': {'file': '文件', 'basemap': '底图', 'title': '标题', 'padding_m': '边距米'},
    '检查空间结果': {'distance_tables': '距离表', 'layers': '图层'},
}
SPATIAL_KEYS = {'distance_tables': '距离表', 'layers': '图层'}
DISTANCE_KEYS = {
    'file': '文件', 'origin_record': '起点记录',
    'destination_longitude_column': '终点经度列',
    'destination_latitude_column': '终点纬度列',
    'destination_crs': '终点坐标系', 'distance_column': '距离列', 'distance_unit': '距离单位',
}
ORIGIN_KEYS = {'file': '文件', 'path': '路径', 'longitude_field': '经度字段',
               'latitude_field': '纬度字段', 'crs': '坐标系'}
UNITS = {'m': '米', 'metre': '米', 'metres': '米', 'meter': '米', 'meters': '米',
         'km': '千米', 'kilometre': '千米', 'kilometres': '千米',
         'kilometer': '千米', 'kilometers': '千米', 'ft': '英尺', 'foot': '英尺', 'feet': '英尺'}


def _rename(value, aliases, transforms=None):
    """Rename one schema level and reject contradictory bilingual aliases."""
    if not isinstance(value, dict):
        return value
    transforms = transforms or {}
    output = {}
    for key, item in value.items():
        target = aliases.get(key, key)
        if target in transforms:
            item = transforms[target](item)
        if target in output and output[target] != item:
            raise ValueError(f'Conflicting action fields: {target}')
        output[target] = item
    return output


def _reference_fields(value, english=False):
    """Translate pure reference objects; names in arbitrary data remain literal."""
    if isinstance(value, list):
        return [_reference_fields(item, english) for item in value]
    if not isinstance(value, dict):
        return value
    reserved = {'result', 'path', '结果', '路径'}
    if ('result' in value or '结果' in value) and set(value) <= reserved:
        aliases = {'结果': 'result', '路径': 'path'} if english else {'result': '结果', 'path': '路径'}
        # Paths are literal keys/indices into output data, not protocol fields.
        return _rename(value, aliases)
    return {key: _reference_fields(item, english) for key, item in value.items()}


def english_result_references(value):
    """Return legacy result references as result/path objects for model messages."""
    return _reference_fields(value, english=True)


def _unit(value):
    return UNITS.get(value.lower(), value) if isinstance(value, str) else value


def _distance_tables(value):
    if not isinstance(value, list):
        return value
    return [_rename(item, DISTANCE_KEYS, {
        '起点记录': lambda v: _rename(v, ORIGIN_KEYS), '距离单位': _unit,
    }) for item in value]


def _spatial_check(value):
    return _rename(value, SPATIAL_KEYS, {'距离表': _distance_tables})


def _artifacts(value):
    if not isinstance(value, list):
        return value
    return [_rename(item, {'file': '文件', 'description': '说明'}) for item in value]


def normalize_action(value):
    """Convert an English/mixed action to the existing Chinese execution contract.

    Unknown fields and user text remain unchanged. Schema validation still belongs
    to the action handlers. Conflicting bilingual aliases raise ValueError instead
    of silently selecting either value. The supplied dictionary is not mutated.
    """
    if not isinstance(value, dict):
        raise ValueError('Action must be a JSON object')
    normalized = _rename(value, COMMON_KEYS, {
        '动作': lambda name: ACTION_NAMES.get(name, name) if isinstance(name, str) else name,
    })
    name = normalized.get('动作')
    keys = ACTION_KEYS.get(name, {}) if isinstance(name, str) else {}
    transforms = {}
    if name == '提交':
        transforms = {'成果': _artifacts, '空间检查': _spatial_check}
    elif name == '检查空间结果':
        transforms = {'距离表': _distance_tables}
    elif name == '专业工具':
        transforms = {'参数': _reference_fields}
    return _rename(normalized, keys, transforms)
