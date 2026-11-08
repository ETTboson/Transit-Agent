"""日常入口额外保护继承成果与下载原件，沿用历史计算环境。"""
from pathlib import Path
import os
import runpy
import sys
import json

work = Path(sys.argv[2]).resolve()
readonly = [work / '前次结果', work / '新资料']
public = Path(sys.argv[1]).resolve()
contract = json.loads(Path(sys.argv[4]).read_text(encoding='utf-8')) if len(sys.argv) > 4 else None
allowed = {Path(p).resolve() for p in contract['可读']} if contract else set()
immutable = {Path(p).resolve() for p in contract.get('只读', [])} if contract else set()
rewritable = {Path(p).resolve() for p in contract.get('可重写', [])} if contract else set()
allowed.add(Path(sys.argv[3]).resolve())
created = set()
tracked = {Path(p).resolve() for p in contract.get('追踪读取', [])} if contract else set()
read_inputs = set()
automatic = bool(contract and contract.get('自动记录读写'))
written_outputs = set()


def protect_evidence(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0])).resolve()
        mode, flags = args[1] or '', args[2] or 0
        writing = any(c in mode for c in 'wax+') or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        if writing and any(path.is_relative_to(p) for p in readonly):
            raise PermissionError('前次结果和新资料只读；请用新文件保存本次分析')
        if contract and (path.is_relative_to(work) or path.is_relative_to(public)):
            if writing:
                if path in immutable or path.is_relative_to(public):
                    raise PermissionError('任务输入只读')
                if path.exists() and path not in allowed and path not in created and path not in rewritable:
                    raise PermissionError('不能覆盖其他任务的文件')
                if path in rewritable and path not in allowed and path not in created and not ('w' in mode or flags & os.O_TRUNC):
                    raise PermissionError('停用工作文件需覆盖重写，不能追加或读改旧值')
                created.add(path)
                if automatic: written_outputs.add(path)
            elif path not in allowed and path not in created:
                raise PermissionError('未声明的任务输入：请读取任务输入.json或当前任务的上游成果；需要其他资料先更新计划')
            elif path in tracked:
                read_inputs.add(path)


sys.addaudithook(protect_evidence)
try:
    runpy.run_path(str(Path(__file__).resolve().with_name('code_worker.py')), run_name='__main__')
finally:
    if contract and contract.get('读取回执'):
        receipt = Path(contract['读取回执']).resolve()
        # 回执在用户代码结束后由执行器写出，不将其视作模型成果。
        allowed.add(receipt)
        if automatic:
            record = {'读取': [str(p) for p in sorted(read_inputs)],
                      '写入': [p.relative_to(work).as_posix() for p in sorted(written_outputs)]}
        else:
            record = [p.relative_to(work).as_posix() for p in sorted(read_inputs)]
        receipt.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
