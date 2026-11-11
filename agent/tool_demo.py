"""Offline dependency-update example using synthetic directed transport networks."""
import json
from pathlib import Path
import tempfile
from .tool_graph import ToolGraph


def main():
    with tempfile.TemporaryDirectory(prefix='transit-tools-') as tmp:
        root=Path(tmp);data=root/'data';data.mkdir();first=root/'first';first.mkdir()
        network={'directed':True,'nodes':[{'id':'A'},{'id':'B'},{'id':'C'}],
                 'edges':[{'source':'A','target':'B','time_seconds':120,'mode':'walk'},
                          {'source':'B','target':'C','time_seconds':180,'mode':'walk'},
                          {'source':'A','target':'C','time_seconds':400,'mode':'walk'}]}
        for name in ('east.json','west.json'):
            (data/name).write_text(json.dumps(network),encoding='utf-8')
        graph=ToolGraph(first,data)
        for task,name in [('east','east.json'),('west','west.json')]:
            result=graph.execute(task,'Shortest Path',{'graph_file':name,'origin':'A','destination':'C'})
            print(task,json.dumps(result['结果'],ensure_ascii=False))
        # A new source version is deliberately supplied for one independent branch.
        network['edges'][1]['time_seconds']=500
        (data/'east.json').write_text(json.dumps(network),encoding='utf-8')
        second=root/'second';second.mkdir();graph=ToolGraph(second,data,previous=first)
        for task,name in [('east','east.json'),('west','west.json')]:
            result=graph.execute(task,'Shortest Path',{'graph_file':name,'origin':'A','destination':'C'})
            print(task,json.dumps({'更新':result['依赖链'],'结果':result['结果']},ensure_ascii=False))
        print('Synthetic functional example complete; no model API or benchmark run.')


if __name__=='__main__':main()
