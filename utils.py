import os
import sys
import glob
from pathlib import Path
import importlib.util
from typing import Union


def load_script(script_path: str, func_name: str, venv_path: str = None):
    """
    从指定脚本加载函数，可选激活虚拟环境的依赖。
    
    Args:
        script_path: Python 脚本的绝对路径
        func_name: 要加载的函数名
        venv_path: 虚拟环境根目录（如 /path/to/.venv），为 None 则不做额外处理
    
    Returns:
        加载到的函数对象
    """
    script_path = Path(script_path)

    # 如果指定了虚拟环境，把其 site-packages 加入 sys.path
    if venv_path:
        venv_path = Path(venv_path)
        # 兼容 lib/pythonX.Y/site-packages 的目录结构
        site_packages = glob.glob(str(venv_path / "lib" / "python*" / "site-packages"))
        for sp in site_packages:
            if sp not in sys.path:
                sys.path.insert(0, sp)

    # 把脚本所在目录也加入 sys.path，以支持脚本的相对导入
    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    spec = importlib.util.spec_from_file_location(func_name, script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, func_name)