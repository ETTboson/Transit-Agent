from copy import deepcopy
import unittest

from agent.action_protocol import english_result_references, normalize_action


class ActionProtocolTests(unittest.TestCase):
    def test_simple_actions_and_shared_fields(self):
        cases = [
            ({'action': 'run_code', 'code': 'print("file")'}, {'动作': '运行代码', '代码': 'print("file")'}),
            ({'action': 'search_official', 'query': '公交'}, {'动作': '检索官方资料', '检索词': '公交'}),
            ({'action': 'fetch_official', 'url': 'https://www.mbta.com/'}, {'动作': '获取官方资料', '地址': 'https://www.mbta.com/'}),
            ({'action': 'draw_map', 'file': 'map.geojson', 'basemap': 'roads.geojson', 'title': 'Routes', 'padding_m': 250},
             {'动作': '绘制地图', '文件': 'map.geojson', '底图': 'roads.geojson', '标题': 'Routes', '边距米': 250}),
        ]
        for source, expected in cases:
            with self.subTest(action=source['action']):
                source.update(assessment='ready', reason='requested')
                expected.update(当前判断='ready', 理由='requested')
                self.assertEqual(normalize_action(source), expected)

    def test_submit_artifacts_keep_text_and_data_properties(self):
        source = {'action': 'submit', 'conclusion': '已完成', 'evidence': [{'file': 'source.txt', 'description': 'Evidence data'}],
                  'unresolved': ['Unknown'], 'artifacts': [{'file': 'table.csv', 'description': 'OD table', 'properties': {'file': 'literal'}}]}
        result = normalize_action(source)
        self.assertEqual(result, {'动作': '提交', '结论': '已完成', '依据': source['evidence'], '待解决': ['Unknown'],
                                  '成果': [{'文件': 'table.csv', '说明': 'OD table', 'properties': {'file': 'literal'}}]})

    def test_professional_params_and_only_pure_result_refs(self):
        source = {'action': 'professional_tool', 'task': 'route', 'tool': 'Shortest Path', 'file_dependencies': ['rules.txt'],
                  'params': {'graph': {'result': 'feed', 'path': ['graph']}, 'origin': 'A', 'destination': 'B',
                             'file': 'literal', 'title': 'unchanged', 'path': ['native_path'], 'distance_unit': 'm',
                             'rows': [{'result': 4, 'path': 'literal', 'quality': 'measured'}, {'properties': {'file': 'a'}}]}}
        original = deepcopy(source)
        result = normalize_action(source)
        self.assertEqual(result['参数']['graph'], {'结果': 'feed', '路径': ['graph']})
        self.assertEqual(result['参数']['rows'], source['params']['rows'])
        for key in ('file', 'title', 'path', 'distance_unit'):
            self.assertEqual(result['参数'][key], source['params'][key])
        self.assertEqual(result['资料依赖'], ['rules.txt'])
        self.assertEqual(result['工具'], 'Shortest Path')
        self.assertEqual(source, original)

    def spatial_table(self):
        return {'file': 'distances.csv', 'origin_record': {'file': 'source.json', 'path': ['features', 0, 'properties'],
                'longitude_field': 'file', 'latitude_field': 'title', 'crs': 'EPSG:4326'},
                'destination_longitude_column': 'lon', 'destination_latitude_column': 'lat',
                'destination_crs': 'EPSG:4326', 'distance_column': 'length', 'distance_unit': 'm'}

    def test_nested_spatial_check_and_submission(self):
        table = self.spatial_table()
        expected_table = {'文件': 'distances.csv', '起点记录': {'文件': 'source.json', '路径': ['features', 0, 'properties'],
                          '经度字段': 'file', '纬度字段': 'title', '坐标系': 'EPSG:4326'}, '终点经度列': 'lon',
                          '终点纬度列': 'lat', '终点坐标系': 'EPSG:4326', '距离列': 'length', '距离单位': '米'}
        expected = {'距离表': [expected_table], '图层': ['map.geojson']}
        source = {'distance_tables': [table], 'layers': ['map.geojson']}
        self.assertEqual(normalize_action({'action': 'check_spatial', **source}), {'动作': '检查空间结果', **expected})
        result = normalize_action({'action': 'submit', 'conclusion': 'Done', 'spatial_check': source})
        self.assertEqual(result['空间检查'], expected)

    def test_spatial_distance_units_only(self):
        for unit, expected in [('m', '米'), ('metres', '米'), ('km', '千米'), ('kilometres', '千米'), ('ft', '英尺'), ('feet', '英尺')]:
            with self.subTest(unit=unit):
                table = {**self.spatial_table(), 'distance_unit': unit}
                result = normalize_action({'action': 'check_spatial', 'distance_tables': [table]})
                self.assertEqual(result['距离表'][0]['距离单位'], expected)

    def test_legacy_actions_unchanged(self):
        cases = [
            {'动作': '运行代码', '代码': 'print("中文")', '当前判断': '继续', '理由': '必要'},
            {'动作': '专业工具', '任务': 'route', '工具': 'Shortest Path', '参数': {'graph': {'结果': 'feed', '路径': ['graph']}}},
            {'动作': '提交', '结论': '完成', '成果': [{'文件': 'result.csv', '说明': '结果'}],
             '空间检查': {'距离表': [{'文件': 'a.csv', '距离单位': '米'}], '图层': ['map.geojson']}},
            {'动作': '检查空间结果', '图层': ['map.geojson']},
        ]
        for source in cases:
            with self.subTest(action=source['动作']):
                original = deepcopy(source)
                self.assertEqual(normalize_action(source), original)
                self.assertEqual(source, original)

    def test_equal_bilingual_aliases_are_unambiguous(self):
        source = {'action': 'submit', '动作': '提交', 'conclusion': 'Done', '结论': 'Done',
                  'artifacts': [{'file': 'a.csv', 'description': 'table'}], '成果': [{'文件': 'a.csv', '说明': 'table'}]}
        self.assertEqual(normalize_action(source), {'动作': '提交', '结论': 'Done', '成果': [{'文件': 'a.csv', '说明': 'table'}]})
        mixed_ref = {'action': 'professional_tool', 'params': {'graph': {'result': 'feed', '结果': 'feed', 'path': ['graph'], '路径': ['graph']}}}
        self.assertEqual(normalize_action(mixed_ref)['参数']['graph'], {'结果': 'feed', '路径': ['graph']})

    def test_conflicting_aliases_fail_at_every_schema_level(self):
        cases = [
            {'action': 'submit', '动作': '运行代码'},
            {'action': 'submit', 'conclusion': 'yes', '结论': 'no'},
            {'action': 'draw_map', 'file': 'a', '文件': 'b'},
            {'action': 'submit', 'artifacts': [{'file': 'a', '文件': 'b'}]},
            {'action': 'submit', 'spatial_check': {'layers': ['a'], '图层': ['b']}},
            {'action': 'check_spatial', 'distance_tables': [{'origin_record': {'file': 'a', '文件': 'b'}}]},
            {'action': 'check_spatial', 'distance_tables': [{'distance_unit': 'm', '距离单位': '千米'}]},
            {'action': 'professional_tool', 'params': {'graph': {'result': 'a', '结果': 'b'}}},
            {'action': 'professional_tool', 'params': {'graph': {'result': 'a', 'path': [], '路径': ['graph']}}},
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaises(ValueError):
                normalize_action(source)

    def test_english_result_refs_preserve_native_properties_and_paths(self):
        source = {'params': {'graph': {'结果': 'feed', '路径': ['结果', 0]},
                             'list': [{'结果': 'other'}], 'properties': {'结果': 'measured', '标签': 'native'},
                             'file': 'unchanged'}, 'result_ref': {'result': 'already', 'path': []}}
        result = english_result_references(source)
        self.assertEqual(result['params']['graph'], {'result': 'feed', 'path': ['结果', 0]})
        self.assertEqual(result['params']['list'], [{'result': 'other'}])
        self.assertEqual(result['params']['properties'], source['params']['properties'])
        self.assertEqual(result['result_ref'], source['result_ref'])
        self.assertIn('结果', source['params']['graph'])
        with self.assertRaises(ValueError):
            english_result_references({'结果': 'a', 'result': 'b'})

    def test_unknown_fields_are_not_general_translation_targets(self):
        source = {'action': 'run_code', 'code': 'pass', 'payload': {'action': 'submit', 'file': 'data'}, 'file': 'arbitrary'}
        result = normalize_action(source)
        self.assertEqual(result['payload'], source['payload'])
        self.assertEqual(result['file'], 'arbitrary')
        self.assertEqual(normalize_action({'action': 'future_action', 'query': 'literal'}), {'动作': 'future_action', 'query': 'literal'})
        with self.assertRaises(ValueError):
            normalize_action(['not', 'an', 'object'])


if __name__ == '__main__':
    unittest.main()
