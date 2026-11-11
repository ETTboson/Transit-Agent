"""Dependency-tracked professional tool calls, persisted across planning sessions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import time

CACHE_VERSION = 1


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class ToolGraph:
    def __init__(self, folder, data, previous=None, registry=None, file_parameters=None):
        self.managed = registry is None
        if registry is None:
            from .tools import transit_network, transit_spatial
            registry = {**transit_network.TOOLS, **transit_spatial.TOOLS}
            file_parameters = {**transit_network.FILE_PARAMETERS, **transit_spatial.FILE_PARAMETERS}
        self.registry, self.file_parameters = registry, file_parameters or {}
        self.folder, self.data = Path(folder).resolve(), Path(data).resolve()
        self.outputs = self.folder / 'tool_results'
        self.outputs.mkdir(exist_ok=True)
        self.nodes = {}
        self.events = []
        self.calls, self.seconds = 0, 0.0
        if previous and (Path(previous) / 'tool_graph.json').is_file():
            saved = json.loads((Path(previous) / 'tool_graph.json').read_text(encoding='utf-8'))
            if saved['version'] == CACHE_VERSION:
                self.nodes = saved['nodes']
                for node_id, node in self.nodes.items():
                    self._id(node_id)
                    source = Path(previous) / 'tool_results' / (node_id + '.json')
                    if source.is_file():
                        shutil.copy2(source, self.outputs / source.name)
                self._restore_inputs(Path(previous).resolve())
        self.refresh()

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', value):
            raise ValueError('任务编号须以英文字母开头，仅含字母、数字、下划线或连字符，最长64字符')

    def save(self):
        payload = {'version': CACHE_VERSION, 'nodes': self.nodes}
        (self.folder / 'tool_graph.json').write_bytes(encoded(payload))

    @staticmethod
    def _refs(value):
        if isinstance(value, dict):
            if '结果' in value:
                if set(value) - {'结果', '路径'}:
                    raise ValueError('结果引用仅允许结果和路径字段')
                yield value['结果']
            else:
                for child in value.values(): yield from ToolGraph._refs(child)
        elif isinstance(value, list):
            for child in value: yield from ToolGraph._refs(child)

    def _restore_inputs(self, previous):
        """Carry only recorded run inputs forward; current supplied data wins."""
        for node in self.nodes.values():
            for location in node.get('file_locations', {}).values():
                if location.get('scope') != 'run': continue
                relative = Path(location['path'])
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('保存的运行文件位置越界')
                source, target = (previous / relative).resolve(), (self.folder / relative).resolve()
                if not source.is_relative_to(previous) or not target.is_relative_to(self.folder):
                    raise ValueError('保存的运行文件位置越界')
                supplied = (self.data / relative).resolve()
                if (supplied.is_relative_to(self.data) and supplied.is_file()) or target.exists():
                    continue
                if source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)

    def _file(self, name, node=None):
        if not isinstance(name, str):
            raise ValueError('文件参数必须为资料目录或本次工作目录内的路径')
        for base in (self.data, self.folder):
            path = (base / name).resolve()
            if path.is_relative_to(base) and path.is_file():
                return path
        # Absolute references from an earlier session rebase through recorded origins.
        location = (node or {}).get('file_locations', {}).get(name)
        if location:
            relative = Path(location['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('保存的输入文件位置越界')
            bases = (self.data, self.folder) if location['scope'] == 'run' else (self.data,)
            for base in bases:
                path = (base / relative).resolve()
                if path.is_relative_to(base) and path.is_file(): return path
        raise ValueError('找不到本次资料范围内的文件：' + name)

    def _location(self, path):
        if path.is_relative_to(self.data):
            return {'scope': 'data', 'path': path.relative_to(self.data).as_posix()}
        return {'scope': 'run', 'path': path.relative_to(self.folder).as_posix()}

    def _result_source(self, name, node):
        if not isinstance(name, str): return None
        if (self.data / name).resolve().is_relative_to(self.data) and (self.data / name).is_file():
            return None
        location = node.get('file_locations', {}).get(name)
        path = (self.folder / (location['path'] if location and location['scope']=='run' else name)).resolve()
        return path.stem if path.parent == self.outputs and path.suffix == '.json' else None

    def _dependencies(self, node):
        dependencies=set(self._refs(node['params']))
        names=[node['params'].get(field) for field in self.file_parameters.get(node['tool'], ())]
        for name in names+node.get('files', []):
            parent=self._result_source(name,node)
            if parent: dependencies.add(parent)
        return dependencies

    def _invalidate(self, keys, reason):
        invalid = set(keys)
        while True:
            additions = {key for key, node in self.nodes.items() if key not in invalid and
                         (self._dependencies(node) | set(node.get('dependencies', {}))) & invalid}
            if not additions: break
            invalid.update(additions)
        for key in invalid:
            if key in self.nodes:
                self.nodes[key].update(status='invalid', error=reason)

    def refresh(self):
        """Mark changed, missing or invalid outputs and descendants without computing."""
        invalid = set()
        for key, node in self.nodes.items():
            if node.get('status') != 'valid':
                invalid.add(key)
                continue
            try:
                output = self.outputs / (key + '.json')
                if not output.is_file() or digest(output) != node.get('output_digest'):
                    invalid.add(key)
                if any(digest(self._file(name, node)) != version
                       for name, version in node.get('source_versions', {}).items()):
                    invalid.add(key)
                for parent, signature in node.get('dependencies', {}).items():
                    if parent not in self.nodes or self.nodes[parent].get('signature') != signature:
                        invalid.add(key)
            except (OSError, ValueError, TypeError):
                invalid.add(key)
        self._invalidate(invalid, '输入或上游结果已改变，需要重新调用核验')
        self.save()
        return self.invalid_results()

    def invalid_results(self):
        return ['tool_results/' + key + '.json' for key, node in sorted(self.nodes.items())
                if node.get('status') != 'valid']

    def execute(self, node_id, tool, params, file_dependencies=None, max_calls=10, max_seconds=360):
        self._id(node_id)
        if tool not in self.registry or not isinstance(params, dict):
            raise ValueError('专业工具名或参数无效')
        files = file_dependencies or []
        if not isinstance(files, list) or any(not isinstance(x, str) for x in files):
            raise ValueError('资料依赖必须是文件路径列表')
        # Validate the proposed graph before changing existing records.
        candidate = {'tool': tool, 'params': deepcopy(params), 'files': files}
        records = {**self.nodes, node_id: candidate}
        def check(key, stack):
            self._id(key)
            if key in stack: raise ValueError('任务依赖不能构成环')
            if key not in records: raise ValueError('未知上游结果：' + key)
            for dep in self._dependencies(records[key]): check(dep, stack + [key])
        check(node_id, [])
        self.refresh()
        old = self.nodes.get(node_id, {})
        if any(old.get(field) != candidate[field] for field in candidate):
            self._invalidate({node_id}, '任务参数已更新，需要重新计算受影响结果')
        self.nodes[node_id] = {**old, **candidate}
        start_calls, start_seconds = self.calls, self.seconds
        self.events = []
        visited = {}

        def evaluate(key):
            if key in visited: return visited[key]
            node = self.nodes[key]
            upstream = {}
            files_used = {}
            file_locations = {}
            def resolve(value):
                if isinstance(value, dict):
                    if '结果' in value:
                        parent = value['结果']
                        result = evaluate(parent)
                        upstream[parent] = self.nodes[parent]['signature']
                        path = value.get('路径', [])
                        if not isinstance(path, list): raise ValueError('结果路径必须是字段或索引列表')
                        for field in path: result = result[field]
                        return deepcopy(result)
                    return {k: resolve(v) for k, v in value.items()}
                if isinstance(value, list): return [resolve(v) for v in value]
                return value
            try:
                for parent in sorted(self._dependencies(node)):
                    evaluate(parent)
                    upstream[parent]=self.nodes[parent]['signature']
                parameters = resolve(node['params'])
                signature_params = deepcopy(parameters)
                for param in self.file_parameters.get(node['tool'], ()):
                    if param in parameters:
                        path = self._file(parameters[param], node)
                        files_used[parameters[param]] = digest(path)
                        file_locations[parameters[param]] = self._location(path)
                        parameters[param] = str(path)
                for name in node['files']:
                    path = self._file(name, node)
                    files_used[name] = digest(path)
                    file_locations[name] = self._location(path)
                signature = hashlib.sha256(encoded([CACHE_VERSION, node['tool'], signature_params, files_used, upstream])).hexdigest()
                output = self.outputs / (key + '.json')
                if (node.get('status') == 'valid' and node.get('signature') == signature
                        and output.is_file() and digest(output) == node.get('output_digest')):
                    result = json.loads(output.read_text(encoding='utf-8'))
                    self.events.append({'任务': key, '状态': '复用'})
                else:
                    if self.calls - start_calls >= max_calls or self.seconds - start_seconds >= max_seconds:
                        raise ValueError('专业工具计算预算已用尽')
                    self.calls += 1
                    started = time.perf_counter()
                    try:
                        remaining = max_seconds - (self.seconds - start_seconds)
                        if self.managed:
                            from .tools.runner import run_tool
                            result = run_tool(node['tool'], parameters, remaining)
                        else:
                            result = self.registry[node['tool']](parameters)
                        if time.perf_counter() - started > remaining:
                            raise TimeoutError('专业工具计算时间预算已用尽')
                        content = encoded(result)
                    finally:
                        self.seconds += time.perf_counter() - started
                    output.write_bytes(content)
                    node.update(signature=signature, output_digest=digest(output), status='valid',
                                source_versions=files_used, file_locations=file_locations, dependencies=upstream)
                    node.pop('error', None)
                    self.events.append({'任务': key, '状态': '计算'})
                visited[key] = result
                return result
            except Exception as exc:
                self._invalidate({key}, str(exc))
                raise
        try:
            result = evaluate(node_id)
            return {'结果引用': {'结果': node_id, '路径': []}, '文件': 'tool_results/' + node_id + '.json',
                    '结果': result, '依赖链': self.events.copy()}
        finally:
            self.save()

    def describe(self):
        return [{'任务': key, '工具': n['tool'], '参数': n['params'], '资料依赖': n['files'],
                 '状态': n.get('status', 'invalid')} for key, n in self.nodes.items()]
