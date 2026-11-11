import json
from pathlib import Path
import tempfile
import time
import unittest

from agent.tool_graph import ToolGraph


class ToolGraphTests(unittest.TestCase):
    def test_result_file_reference_builds_dependency_and_updates_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'source.json').write_text('2')
            registry={'read':lambda p:json.loads(Path(p['file']).read_text())}
            graph=ToolGraph(root,root,registry=registry,file_parameters={'read':('file',)})
            graph.execute('a','read',{'file':'source.json'})
            # A separate input directory distinguishes managed outputs from supplied data.
            data=root/'inputs';data.mkdir();(data/'source.json').write_text('2');graph.data=data
            graph.execute('b','read',{'file':'tool_results/a.json'})
            (data/'source.json').write_text('9')
            result=graph.execute('b','read',{'file':'tool_results/a.json'})
            self.assertEqual(result['结果'],9)
            self.assertEqual([x['任务'] for x in result['依赖链'] if x['状态']=='计算'],['a','b'])

    def test_changed_source_recomputes_only_affected_branch_across_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();old=root/'old';old.mkdir()
            (data/'a.json').write_text('2');(data/'b.json').write_text('7')
            registry={'read':lambda p:json.loads(Path(p['file']).read_text()),'sum':lambda p:sum(p['values'])}
            files={'read':('file',)}
            graph=ToolGraph(old,data,registry=registry,file_parameters=files)
            graph.execute('a','read',{'file':'a.json'})
            graph.execute('b','read',{'file':'b.json'})
            params={'values':[{'结果':'a'},{'结果':'b'}]}
            self.assertEqual(graph.execute('total','sum',params)['结果'],9)
            (data/'b.json').write_text('10')
            new=root/'new';new.mkdir()
            graph=ToolGraph(new,data,previous=old,registry=registry,file_parameters=files)
            result=graph.execute('total','sum',params)
            self.assertEqual(result['结果'],12)
            self.assertEqual(result['依赖链'],[{'任务':'a','状态':'复用'},{'任务':'b','状态':'计算'},{'任务':'total','状态':'计算'}])
            self.assertEqual(graph.calls,2)
            self.assertEqual(json.loads((old/'tool_results/total.json').read_text()),9)
            self.assertEqual(graph.execute('total','sum',params,max_calls=0)['结果'],12)
            self.assertEqual(graph.calls,2)

    def test_parameters_rules_and_output_tampering_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'rules.txt').write_text('rule1')
            graph=ToolGraph(root,root,registry={'value':lambda p:p['n']})
            graph.execute('n','value',{'n':1},['rules.txt'])
            graph.execute('n','value',{'n':2},['rules.txt'])
            (root/'rules.txt').write_text('rule2')
            graph.execute('n','value',{'n':2},['rules.txt'])
            (root/'tool_results/n.json').write_text('999')
            self.assertEqual(graph.execute('n','value',{'n':2},['rules.txt'])['结果'],2)
            self.assertEqual(graph.calls,4)

    def test_cycle_unknown_ref_budget_and_outside_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);graph=ToolGraph(root,root,registry={'value':lambda p:p},file_parameters={'value':('file',)})
            with self.assertRaises(ValueError):graph.execute('x','value',{'up':{'结果':'missing'}})
            graph.execute('a','value',{'n':1})
            graph.execute('b','value',{'up':{'结果':'a'}})
            with self.assertRaises(ValueError):graph.execute('a','value',{'up':{'结果':'b'}})
            with self.assertRaises(ValueError):graph.execute('c','value',{'n':3},max_calls=0)
            with self.assertRaises(ValueError):graph.execute('d','value',{'file':'../outside.txt'})
            self.assertEqual(graph.nodes['a']['params'],{'n':1})

    def test_failed_update_does_not_make_old_result_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def calc(p):return 10/p['n']
            graph=ToolGraph(root,root,registry={'divide':calc})
            graph.execute('a','divide',{'n':2})
            with self.assertRaises(ZeroDivisionError):graph.execute('a','divide',{'n':0})
            self.assertEqual(graph.nodes['a']['status'],'invalid')
            with self.assertRaises(ZeroDivisionError):graph.execute('a','divide',{'n':0})

    def test_resume_carries_recorded_runtime_inputs_and_rebases_absolute_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();old=root/'old';old.mkdir()
            (old/'prepared').mkdir();source=old/'prepared'/'input.json';source.write_text('4')
            (old/'not_used.txt').write_text('do not inherit')
            registry={'read':lambda p:int(Path(p['file']).read_text())}
            graph=ToolGraph(old,data,registry=registry,file_parameters={'read':('file',)})
            graph.execute('a','read',{'file':'prepared/input.json'})
            graph.execute('absolute','read',{'file':str(source)})
            new=root/'new';new.mkdir()
            graph=ToolGraph(new,data,previous=old,registry=registry,file_parameters={'read':('file',)})
            self.assertEqual((new/'prepared/input.json').read_text(),'4')
            self.assertFalse((new/'not_used.txt').exists())
            self.assertEqual(graph.execute('a','read',{'file':'prepared/input.json'},max_calls=0)['结果'],4)
            self.assertEqual(graph.execute('absolute','read',{'file':str(source)},max_calls=0)['结果'],4)
            self.assertEqual(graph.calls,0)

    def test_current_data_and_existing_runtime_input_win_over_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();old=root/'old';old.mkdir()
            (old/'prepared.json').write_text('4');(old/'other.json').write_text('5')
            registry={'read':lambda p:int(Path(p['file']).read_text())}
            graph=ToolGraph(old,data,registry=registry,file_parameters={'read':('file',)})
            graph.execute('a','read',{'file':'prepared.json'})
            graph.execute('b','read',{'file':'other.json'})
            new=root/'new';new.mkdir();(data/'prepared.json').write_text('9');(new/'other.json').write_text('12')
            graph=ToolGraph(new,data,previous=old,registry=registry,file_parameters={'read':('file',)})
            self.assertFalse((new/'prepared.json').exists())
            self.assertEqual((new/'other.json').read_text(),'12')
            self.assertEqual(graph.invalid_results(),['tool_results/a.json','tool_results/b.json'])
            self.assertEqual(graph.execute('a','read',{'file':'prepared.json'})['结果'],9)
            self.assertEqual(graph.execute('b','read',{'file':'other.json'})['结果'],12)

    def test_refresh_invalidates_descendants_without_computation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.json';source.write_text('2')
            registry={'read':lambda p:int(Path(p['file']).read_text()), 'double':lambda p:2*p['value']}
            graph=ToolGraph(root,root,registry=registry,file_parameters={'read':('file',)})
            graph.execute('a','read',{'file':'source.json'})
            graph.execute('b','double',{'value':{'结果':'a'}})
            graph.execute('c','double',{'value':{'结果':'b'}})
            graph.execute('independent','double',{'value':7})
            calls=graph.calls;source.write_text('3')
            self.assertEqual(graph.refresh(),['tool_results/a.json','tool_results/b.json','tool_results/c.json'])
            self.assertEqual(graph.calls,calls)
            self.assertEqual(graph.nodes['independent']['status'],'valid')
            self.assertEqual(graph.execute('c','double',{'value':{'结果':'b'}})['结果'],12)
            self.assertEqual(graph.invalid_results(),[])

    def test_parameter_change_and_failed_change_invalidate_existing_descendants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            registry={'divide':lambda p:10/p['n'], 'double':lambda p:2*p['value']}
            graph=ToolGraph(root,root,registry=registry)
            graph.execute('a','divide',{'n':2});graph.execute('b','double',{'value':{'结果':'a'}})
            graph.execute('a','divide',{'n':5})
            self.assertEqual(graph.invalid_results(),['tool_results/b.json'])
            self.assertEqual(graph.execute('b','double',{'value':{'结果':'a'}})['结果'],4)
            with self.assertRaises(ZeroDivisionError):graph.execute('a','divide',{'n':0})
            self.assertEqual(graph.invalid_results(),['tool_results/a.json','tool_results/b.json'])

    def test_output_tampering_and_missing_sources_propagate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.json';source.write_text('3')
            registry={'read':lambda p:int(Path(p['file']).read_text()), 'double':lambda p:2*p['value']}
            graph=ToolGraph(root,root,registry=registry,file_parameters={'read':('file',)})
            graph.execute('a','read',{'file':'source.json'});graph.execute('b','double',{'value':{'结果':'a'}})
            (root/'tool_results/a.json').write_text('999')
            self.assertEqual(graph.refresh(),['tool_results/a.json','tool_results/b.json'])
            graph.execute('b','double',{'value':{'结果':'a'}})
            source.unlink()
            self.assertEqual(graph.refresh(),['tool_results/a.json','tool_results/b.json'])

    def test_resume_rejects_escaped_recorded_input_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=root/'old';old.mkdir();new=root/'new';new.mkdir();data=root/'data';data.mkdir()
            graph=ToolGraph(old,data,registry={'value':lambda p:1})
            graph.execute('a','value',{})
            graph.nodes['a']['file_locations']={'bad':{'scope':'run','path':'../outside.txt'}};graph.save()
            with self.assertRaisesRegex(ValueError,'越界'):
                ToolGraph(new,data,previous=old,registry={'value':lambda p:1})

    def test_over_budget_direct_tool_does_not_create_valid_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def slow(params):time.sleep(.02);return 1
            graph=ToolGraph(root,root,registry={'slow':slow})
            with self.assertRaises(TimeoutError):graph.execute('slow','slow',{},max_seconds=.001)
            self.assertEqual(graph.nodes['slow']['status'],'invalid')
            self.assertFalse((root/'tool_results/slow.json').exists())


if __name__=='__main__':unittest.main()
