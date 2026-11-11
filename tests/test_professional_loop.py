import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent import planning
from agent.tools.runner import run_tool


class ProfessionalLoopTests(unittest.TestCase):
    def test_model_actions_use_context_tools_and_resume_without_model_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'inputs';data.mkdir()
            (data/'目录.json').write_text('[]',encoding='utf-8')
            (data/'资料.py').write_text('',encoding='utf-8')
            net={'directed':True,'nodes':[{'id':'A'},{'id':'B'}],
                 'edges':[{'source':'A','target':'B','time_seconds':20,'mode':'walk'}]}
            (data/'net.json').write_text(json.dumps(net),encoding='utf-8')
            action={'动作':'专业工具','任务':'route','工具':'Shortest Path','参数':{'graph_file':'net.json','origin':'A','destination':'B'}}
            final={'动作':'提交','结论':'完成路径计算','成果':[{'文件':'tool_results/route.json'}]}
            stats={'usage':{'prompt_tokens':10,'completion_tokens':10}}
            def actions():return [(json.dumps(action),stats),(json.dumps(final),stats)]
            with patch.object(planning,'ROOT',root), patch.object(planning.engine,'ask',side_effect=actions()), patch('sys.stdout',new_callable=io.StringIO):
                old,trace=planning.run('从A到B',data,'test','test-key')
            self.assertEqual(trace['专业工具次数'],1)
            self.assertIn('TRANSPORT_MODE',trace['初始消息'][0]['content'])
            self.assertTrue((old/'domain_context.json').is_file())
            with patch.object(planning,'ROOT',root), patch.object(planning.engine,'ask',side_effect=actions()), patch('sys.stdout',new_callable=io.StringIO):
                new,trace=planning.run('继续相同路径',data,'test','test-key',old)
            self.assertEqual(trace['专业工具次数'],0)
            self.assertEqual(trace['步骤'][0]['工具反馈']['依赖链'][0]['状态'],'复用')
            net['edges'][0]['time_seconds']=45
            (data/'net.json').write_text(json.dumps(net),encoding='utf-8')
            retry=[(json.dumps(final),stats)]+actions()
            with patch.object(planning,'ROOT',root), patch.object(planning.engine,'ask',side_effect=retry), patch('sys.stdout',new_callable=io.StringIO):
                updated,trace=planning.run('按新输入更新',data,'test','test-key',new)
            self.assertIn('已失效',trace['步骤'][0]['错误'])
            self.assertEqual(trace['专业工具次数'],1)
            result=json.loads((updated/'tool_results/route.json').read_text(encoding='utf-8'))
            self.assertEqual(result['cost'],45)

    def test_real_tool_worker_honors_deadline(self):
        with self.assertRaises(TimeoutError):
            run_tool('Network Analysis',{'graph':{'nodes':[],'edges':[]}},0.001)


if __name__=='__main__':unittest.main()
