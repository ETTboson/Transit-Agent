"""执行单组模型代码。输入只读，组内输出可写；不继承 API 凭据。"""
from pathlib import Path
import sys
import os
import json
import csv
import zipfile
import io
import math
import pandas
import numpy
import pypdf
import pdfplumber
import shapefile
import pyproj
import networkx
import scipy.spatial
import scipy.sparse.csgraph
import shapely
import shapely.ops
import shapely.geometry
from PIL import Image

public,work,script=[Path(p).resolve() for p in sys.argv[1:4]]
sys.path.insert(0,str(public))
if (public/'资料.py').is_file():
    import 资料
protected_inputs={work/p.relative_to(public) for p in public.rglob('*') if p.is_file()}
source=script.read_text(encoding='utf-8')
compiled=compile(source,str(script),'exec')
libraries=[Path(sys.prefix).resolve(),Path(sys.base_prefix).resolve()]

def inside(p,r):return p==r or r in p.parents

def audit(event,args):
    if event.startswith(('socket.','subprocess.','winreg.','ctypes.dlopen')) or event in {'os.system','os.exec','os.spawn','os.remove','os.rmdir','os.rename'}:
        raise PermissionError('此轮只开放资料读取和本地计算')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        p=Path(os.fsdecode(args[0])).resolve();mode=args[1] or '';flags=args[2] or 0
        writing=any(c in mode for c in 'wax+') or bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
        if writing and p in protected_inputs:raise PermissionError('公共资料副本只读，请将结果写入新文件')
        if not (inside(p,work) if writing else any(inside(p,r) for r in [public,work,*libraries])):
            raise PermissionError('只能读取本轮公共资料和本组目录，写入本组目录')
    if event in {'os.listdir','os.scandir'} and args and isinstance(args[0],(str,bytes,os.PathLike)):
        p=Path(os.fsdecode(args[0])).resolve()
        if not any(inside(p,r) for r in [public,work,*libraries]):raise PermissionError('不能查看其他目录')
    if event=='os.mkdir' and not inside(Path(args[0]).resolve(),work):raise PermissionError('不能在本组目录外创建目录')

os.chdir(work)
sys.addaudithook(audit)
exec(compiled,{'__name__':'__main__','__file__':str(script),'数据目录':public,'工作目录':work})
