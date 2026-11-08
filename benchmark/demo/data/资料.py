"""通用资料读取；返回普通文本、明确范围，检索可限定文档并按文档轮转。"""
from pathlib import Path
import json
import re

数据目录 = Path(__file__).resolve().parent


def 目录():
    return json.loads((数据目录 / '目录.json').read_text(encoding='utf-8'))


def 读取(编号, 起始=0, 长度=4000, 页码=None):
    条目 = next(x for x in 目录() if x['编号'] == 编号)
    if not 条目.get('提取文本'):
        return f"{编号} 无文字提取，请按目录结构读取原始文件：{条目['原始文件']}"
    内容 = (数据目录 / 条目['提取文本']).read_text(encoding='utf-8')
    if 页码 is not None:
        标记 = f'【原文第{页码}页】'
        if 标记 not in 内容:
            return f'{编号} 未找到第{页码}页'
        内容 = 内容.split(标记, 1)[1].split('【原文第', 1)[0]
    起始 = max(0, int(起始))
    结束 = min(len(内容), 起始 + max(1, min(int(长度), 12000)))
    提示 = f'后续起始={结束}' if 结束 < len(内容) else '该范围已读完'
    return f"{编号} | {条目['标题']} | 页码={页码} | 字符{起始}:{结束}/{len(内容)} | {提示}\n" + 内容[起始:结束]


def 检索(关键词, 编号=None, 最多=8, 每篇=2):
    范围 = [编号] if isinstance(编号, str) else 编号
    各篇 = []
    for 条目 in 目录():
        if (范围 is not None and 条目['编号'] not in 范围) or not 条目.get('提取文本'):
            continue
        内容 = (数据目录 / 条目['提取文本']).read_text(encoding='utf-8')
        命中 = []
        for m in re.finditer(re.escape(关键词), 内容, re.IGNORECASE):
            前缀 = 内容[:m.start()]
            页 = re.findall(r'【原文第(\d+)页】', 前缀)
            命中.append({'编号': 条目['编号'], '页码': int(页[-1]) if 页 else None,
                         '起始': max(0, m.start()-160), '片段': 内容[max(0, m.start()-160):m.end()+360]})
            if len(命中) >= 每篇:
                break
        if 命中:
            各篇.append(命中)
    # 同一文档不能先占满全库检索结果。
    结果 = [组[i] for i in range(每篇) for 组 in 各篇 if i < len(组)][:最多]
    return json.dumps({'范围': 范围 or '全库', '结果': 结果,
                       '提示': '最多返回指定条数；可限定编号继续检索。没有命中不等于文件没有相关内容。'}, ensure_ascii=False, indent=2)
