"""Run a registered numerical tool in a process with a wall-clock deadline."""
import json
import os
from pathlib import Path
import subprocess
import sys


def run_tool(name, parameters, timeout_seconds):
    if timeout_seconds <= 0:
        raise TimeoutError('专业工具计算时间预算已用尽')
    env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('KEY','TOKEN','SECRET','PASSWORD'))}
    env['PYTHONDONTWRITEBYTECODE']='1'
    try:
        process=subprocess.run([sys.executable,'-B','-X','utf8','-m','agent.tools.runner',name],
            cwd=Path(__file__).resolve().parents[2], input=json.dumps(parameters,ensure_ascii=False,allow_nan=False),
            text=True,encoding='utf-8',capture_output=True,timeout=timeout_seconds,env=env)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError('专业工具超过剩余计算时间，进程已停止') from exc
    if process.returncode:
        raise ValueError(process.stderr.strip() or '专业工具执行失败')
    return json.loads(process.stdout)


def main():
    from . import transit_network, transit_spatial
    registry={**transit_network.TOOLS,**transit_spatial.TOOLS}
    try:
        result=registry[sys.argv[1]](json.load(sys.stdin))
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':main()
