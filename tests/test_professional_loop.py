import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from copy import deepcopy
from unittest.mock import patch

from agent import planning
from agent.tools.runner import run_tool


class ProfessionalLoopTests(unittest.TestCase):
    def test_english_actions_chain_results_and_code_keeps_source_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'inputs';data.mkdir()
            (data/'目录.json').write_text('[{"name":"原始资料"}]',encoding='utf-8')
            (data/'资料.py').write_text('',encoding='utf-8')
            tables={
                'stops.txt':'stop_id,stop_name,stop_lat,stop_lon\nA,First,30,114\nB,Second,30.1,114.1\n',
                'routes.txt':'route_id,route_type\nR,3\n',
                'trips.txt':'route_id,service_id,trip_id\nR,S,T\n',
                'stop_times.txt':'trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT,08:00:00,08:00:00,A,1\nT,08:10:00,08:10:00,B,2\n',
                'calendar_dates.txt':'service_id,date,exception_type\nS,20261113,1\n',
            }
            with zipfile.ZipFile(data/'feed.zip','w') as archive:
                for name,content in tables.items():archive.writestr(name,content)
            actions=iter([
                {'action':'professional_tool','task':'feed','tool':'GTFS Reader','params':{'file':'feed.zip','service_date':'2026-11-13'}},
                {'action':'professional_tool','task':'route','tool':'Multimodal Routing','params':{'graph':{'result':'feed','path':['graph']},'origin':'A','destination':'B','departure_seconds':28740}},
                {'action':'run_code','code':"import json\nassert data_dir == 数据目录 and work_dir == 工作目录\nv=json.loads((work_dir/'tool_results/route.json').read_text())\n(work_dir/'summary.txt').write_text(str(v['travel_seconds']),encoding='utf-8')"},
                {'action':'submit','conclusion':'行程耗时660秒，包含60秒候车。','artifacts':[{'file':'summary.txt','description':'Journey duration'}]},
            ])
            requests=[]
            def ask(key,messages,cap):
                requests.append(deepcopy(messages))
                return json.dumps(next(actions),ensure_ascii=False),{'usage':{'prompt_tokens':10,'completion_tokens':10}}
            repository=planning.ROOT;original_execute=planning.execute
            def execute(*args,**kwargs):
                with patch.object(planning,'ROOT',repository):
                    return original_execute(*args,**kwargs)
            with patch.object(planning,'ROOT',root),patch.object(planning.engine,'ask',side_effect=ask),patch.object(planning,'execute',side_effect=execute),patch('sys.stdout',new_callable=io.StringIO):
                folder,trace=planning.run('从A到B',data,'test','test-key')
            self.assertEqual(trace['步骤'][2]['执行反馈']['退出码'],0,trace['步骤'][2]['执行反馈'])
            self.assertEqual((folder/'summary.txt').read_text(),'660')
            self.assertEqual(trace['最终提交']['结论'],'行程耗时660秒，包含60秒候车。')
            self.assertEqual(trace['步骤'][1]['动作']['参数']['graph'],{'结果':'feed','路径':['graph']})
            self.assertEqual(trace['步骤'][2]['执行反馈']['退出码'],0)
            frames=[m['content'] for m in requests[-1] if m['content'].startswith('Tool feedback ')]
            feedback=json.loads(frames[0].split(': ',1)[1])
            self.assertEqual(feedback['result_ref'],{'result':'feed','path':[]})
            self.assertEqual(feedback['dependency_trace'],[{'task':'feed','status':'computed'}])
            self.assertIn('原始资料',requests[0][1]['content'])

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
