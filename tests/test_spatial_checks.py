import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyproj import Transformer
from agent import planning
from agent.tools import spatial_checks as checks


def fixture(folder):
    (folder/'来源.json').write_text(json.dumps({'x':-71.0,'y':42.0}),encoding='utf-8')
    return {'距离表':[{'文件':'距离.csv', '起点记录':{'文件':'来源.json','路径':[],
        '经度字段':'x','纬度字段':'y','坐标系':'EPSG:4326'},
        '终点经度列':'x','终点纬度列':'y','终点坐标系':'EPSG:4326','距离列':'d','距离单位':'米'}]}


class SpatialChecksTests(unittest.TestCase):
    def test_units_projection_and_missing_distance(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);spec=fixture(folder)
            x,y=Transformer.from_crs(4326,2249,always_xy=True).transform(-71.0,42.001)
            spec['距离表'][0].update({'终点坐标系':'EPSG:2249','距离单位':'英尺'})
            (folder/'距离.csv').write_text(f'x,y,d\n{x},{y},400\n{x},{y},NaN\n{x},{y},-1\n',encoding='utf-8')
            result=checks.check_spatial(folder,spec)
            self.assertEqual(result['结果'][0]['条数'],3)
            self.assertEqual(result['结果'][0]['失败数'],2)
            self.assertEqual([p['行号'] for p in result['结果'][0]['问题']],[3,4])
            spec['距离表'][0]['终点坐标系']='EPSG:4326'
            self.assertEqual(checks.check_spatial(folder,spec)['状态'],'失败')

    def test_submission_rereads_distance_after_a_previous_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);spec=fixture(folder)
            (folder/'距离.csv').write_text('x,y,d\n-71,42.001,120\n',encoding='utf-8')
            self.assertEqual(checks.check_spatial(folder,spec)['状态'],'通过')
            (folder/'距离.csv').write_text('x,y,d\n-71,42.001,0\n',encoding='utf-8')
            result,_=checks.submission_check(folder,{'成果':[]},spec)
            self.assertEqual(result['状态'],'失败')
            self.assertGreater(result['结果'][0]['问题'][0]['直线下界米'],110)

    def test_geojson_submission_is_checked_without_explicit_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            geo={'type':'FeatureCollection','features':[{'type':'Feature','properties':{},
                 'geometry':{'type':'LineString','coordinates':[[-71,42]]}}]}
            (folder/'图.geojson').write_text(json.dumps(geo),encoding='utf-8')
            action={'成果':[{'文件':'图.geojson'}]}
            result,_=checks.submission_check(folder,action)
            self.assertEqual(result['状态'],'失败')
            self.assertIn('至少需要两个坐标',result['结果'][0]['问题'][0]['原因'])
            geo['features'][0]['geometry']['coordinates'].append([-71,42.001])
            (folder/'图.geojson').write_text(json.dumps(geo),encoding='utf-8')
            self.assertEqual(checks.submission_check(folder,action)[0]['状态'],'通过')
            self.assertEqual(checks.submission_check(folder,{'空间检查':{'图层':'图.geojson'}})[0]['状态'],'失败')
            self.assertEqual(checks.check_spatial(folder,{})['状态'],'未检查')

    def test_previous_real_outputs_expose_nine_short_routes_and_invalid_line(self):
        folder=planning.ROOT/'data/planning_runs/20261026_235425_121250'
        if not folder.exists():self.skipTest('本地历史实验未安装')
        spec={'距离表':[{'文件':'成果_入口到69路站点距离与客流_F24F25.csv',
            '起点记录':{'文件':'D33.json','路径':['响应','features',0,'geometry'],
                        '经度字段':'x','纬度字段':'y','坐标系':'EPSG:4326'},
            '终点经度列':'lon','终点纬度列':'lat','终点坐标系':'EPSG:4326',
            '距离列':'dist_m','距离单位':'米'}], '图层':['图_SectionA_入口步行可达性.geojson']}
        result=checks.check_spatial(folder,spec)
        self.assertEqual(result['结果'][0]['条数'],30)
        self.assertEqual(result['结果'][0]['失败数'],9)
        self.assertEqual(result['结果'][1]['失败数'],1)

    def run_simulated(self, repair):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'inputs';data.mkdir();spec=fixture(data)
            (data/'资料.py').write_text('',encoding='utf-8')
            (data/'目录.json').write_text('[]',encoding='utf-8')
            (data/'距离.csv').write_text('x,y,d\n-71,42.001,0\n',encoding='utf-8')
            submit={'动作':'提交','结论':'模拟结果','空间检查':spec,'成果':[{'文件':'距离.csv'}]}
            # 先执行工具，确保退回提交时已有持久化轨迹，而非只测第一步提交。
            actions=[{'动作':'检查空间结果',**spec}]+([submit,{'动作':'运行代码','代码':'模拟修正'},submit] if repair else [submit,submit])
            calls=[]
            def ask(key,messages,cap):
                calls.append(json.loads(json.dumps(messages)))
                return json.dumps(actions[len(calls)-1]), {'usage':{'prompt_tokens':100,'completion_tokens':100}}
            def execute(code,folder,step,remaining):
                (folder/'距离.csv').write_text('x,y,d\n-71,42.001,120\n',encoding='utf-8')
                return {'退出码':0,'秒':0.1,'stdout':'已重算','stderr':''}
            with patch.object(planning,'ROOT',root), patch.object(planning,'MAX_CALLS',len(actions)), \
                 patch.object(planning.engine,'ask',side_effect=ask), patch.object(planning,'execute',side_effect=execute), \
                 patch.object(planning.engine,'PUBLIC',data), patch.object(planning.engine,'MODEL','模拟'), \
                 contextlib.redirect_stdout(io.StringIO()):
                folder,trace=planning.run('测试退回和修正',data,'模拟','不使用密钥')
            self.assertIn('Submission failed the necessary spatial checks',calls[2][-2]['content'])
            self.assertEqual(trace['步骤'][1]['工具反馈']['状态'],'失败')
            self.assertEqual(trace['空间检查']['状态'],'通过' if repair else '失败')
            self.assertEqual(trace['状态'],'模型已提交，结论待复核' if repair else '空间检查失败，分析未完成')
            self.assertIn('空间必要条件检查：'+('通过' if repair else '失败'),(folder/'结果.html').read_text(encoding='utf-8'))

    def test_loop_returns_failed_submission_and_accepts_recalculated_result(self):
        self.run_simulated(True)

    def test_budget_exhaustion_does_not_label_failed_result_as_passed(self):
        self.run_simulated(False)


if __name__=='__main__':unittest.main()
