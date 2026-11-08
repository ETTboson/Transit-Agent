import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import io

from agent.planning import parse_action, render, inherit_results, execute, engine
from agent.tools import planning as tools


class PlanningTests(unittest.TestCase):
    def test_temporary_credential_uses_hidden_prompt_without_environment_write(self):
        from agent import planning
        import os
        before=os.environ.get('DEEPSEEK_API_KEY')
        with patch('sys.argv',['planning','--question','测试问题','--temporary-key']), \
             patch.object(planning.getpass,'getpass',return_value='临时测试值') as prompt, \
             patch.object(planning,'run') as run:
            planning.main()
        prompt.assert_called_once()
        self.assertEqual(run.call_args.args[3],'临时测试值')
        self.assertEqual(os.environ.get('DEEPSEEK_API_KEY'),before)

    def test_complete_json_with_trailing_model_tags(self):
        action,trailing=parse_action('  {"动作":"提交","结论":"完成"}\n</final>')
        self.assertEqual(action['结论'],'完成')
        self.assertEqual(trailing,'</final>')

    def test_truncated_json_is_not_repaired(self):
        with self.assertRaises(ValueError):parse_action('{"动作":"运行代码","代码":"x=')

    def test_view_excludes_inputs_escapes_text_and_survives_missing_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'D28.csv').write_text('private input',encoding='utf-8')
            (p/'地点.csv').write_text('地点,变化\nA,20\n',encoding='utf-8')
            trace={'问题':'<script>bad</script>','模型':'测试替身','状态':'API调用失败',
                   'tokens':{'输入':0,'输出':0},'步骤':[]}
            render(p,trace,{'D28.csv'})
            text=(p/'结果.html').read_text(encoding='utf-8')
            self.assertIn('本次没有形成有效最终提交',text)
            self.assertNotIn('D28.csv',text)
            self.assertNotIn('<script>bad</script>',text)
            self.assertIn('地点.csv',text)

    def test_followup_keeps_declared_results_and_originals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);previous=root/'old';current=root/'new'
            previous.mkdir();current.mkdir()
            trace={'问题':'原问题','状态':'已提交','步骤':[],
                   '最终提交':{'结论':'待核查','成果':[{'文件':'结果.csv'},{'文件':'../../outside.txt'}]}}
            (previous/'轨迹.json').write_text(json.dumps(trace),encoding='utf-8')
            (previous/'结果.csv').write_text('旧结果',encoding='utf-8')
            (previous/'开发补图.svg').write_text('手工补图',encoding='utf-8')
            (previous/'新资料').mkdir()
            (previous/'新资料/原文.txt').write_text('官方原文',encoding='utf-8')
            context=inherit_results(previous,current)
            self.assertEqual(context['可读成果'],['前次结果/结果.csv'])
            self.assertEqual((previous/'结果.csv').read_text(encoding='utf-8'),'旧结果')
            self.assertFalse((current/'前次结果/开发补图.svg').exists())
            self.assertEqual((current/'前次结果/新资料/原文.txt').read_text(encoding='utf-8'),'官方原文')

    def test_worker_can_read_but_cannot_change_inherited_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'inputs';data.mkdir()
            (data/'资料.py').write_text('',encoding='utf-8')
            folder=root/'run';folder.mkdir();(folder/'前次结果').mkdir()
            old=folder/'前次结果/原表.txt';old.write_text('原值',encoding='utf-8')
            with patch.object(engine,'PUBLIC',data):
                feedback=execute("from pathlib import Path\np=Path('前次结果/原表.txt')\nprint(p.read_text(encoding='utf-8'))\np.write_text('改写',encoding='utf-8')",folder,1,30)
            self.assertNotEqual(feedback['退出码'],0)
            self.assertIn('原值',feedback['stdout'])
            self.assertIn('只读',feedback['stderr'])
            self.assertEqual(old.read_text(encoding='utf-8'),'原值')

    def test_official_sources_reject_lookalikes_and_cross_domain_redirect(self):
        tools.official_url('https://gis.cambridgema.gov/data')
        for url in ['http://mbta.com/x','https://mbta.com.evil.test/x','https://user:secret@mbta.com/x','https://127.0.0.1/x']:
            with self.assertRaises(ValueError):tools.official_url(url)
        with self.assertRaises(ValueError):
            tools.OfficialRedirect().redirect_request(None,None,302,'',{},'https://example.com/file')

    def test_download_keeps_raw_source_text_links_and_dates(self):
        from email.message import Message
        headers=Message();headers['Content-Type']='text/html; charset=utf-8'
        response=io.BytesIO(b'<html><script>ignore me</script><p>Bus update</p><a href="/plan.pdf">Plan</a></html>')
        response.headers=headers;response.url='https://www.mbta.com/project'
        with tempfile.TemporaryDirectory() as tmp, patch.object(tools.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=response
            folder=Path(tmp);feedback=tools.fetch_official(response.url,folder,1)
            record=json.loads((folder/feedback['来源记录']).read_text(encoding='utf-8'))
            self.assertEqual(record['官方链接'],['https://www.mbta.com/plan.pdf'])
            self.assertIsNone(record['发布日期'])
            self.assertIn('ignore me',(folder/record['原始文件']).read_text())
            text=(folder/record['提取文本']).read_text(encoding='utf-8')
            self.assertIn('Bus update',text);self.assertNotIn('ignore me',text)

    def test_map_handles_multiline_and_uses_metre_extent(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            geo={'type':'FeatureCollection','features':[
                {'type':'Feature','properties':{'标签':'A','分组':'站点'},'geometry':{'type':'Point','coordinates':[-71.08,42.37]}},
                {'type':'Feature','properties':{'标签':'B','分组':'道路'},'geometry':{'type':'MultiLineString','coordinates':[
                    [[-71.081,42.37],[-71.08,42.37]], [[-71.08,42.37],[-71.079,42.37]]]}}]}
            (folder/'图层.geojson').write_text(json.dumps(geo),encoding='utf-8')
            feedback=tools.draw_map(folder,{'文件':'图层.geojson','标题':'测试地图','边距米':100},1)
            extent=feedback['范围米']
            # 纬度42.37处经度差0.002约165m，另加两侧各100m；y应为200m。
            self.assertTrue(360 < extent[2]-extent[0] < 370)
            self.assertAlmostEqual(extent[3]-extent[1],200,places=1)
            from PIL import Image
            with Image.open(folder/feedback['图片']) as image:self.assertEqual(image.size,(1800,1200))

    def test_map_reports_missing_fields_instead_of_silent_unnamed_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            data={'type':'FeatureCollection','features':[{'type':'Feature','properties':{'label':'旧站'},
                'geometry':{'type':'Point','coordinates':[-71,42]}}]}
            (folder/'图层.geojson').write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'映射字段名'):
                tools.draw_map(folder,{'文件':'图层.geojson'},1)
            self.assertFalse((folder/'地图1.png').exists())


if __name__=='__main__':unittest.main()
