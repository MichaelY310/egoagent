import json
import os
import re
from pathlib import Path
import importlib.util
import copy
from utils import load_script



def render_knowledge_content(content: str) -> str:
    """渲染 knowledge 模板变量：{{config.key}} 和 {{env.KEY}}"""
    from config import CONFIG
    def replacer(match):
        expr = match.group(1).strip()
        if expr.startswith("config."):
            key = expr[len("config."):]
            return str(CONFIG.get(key, f"{{{{config.{key}}}}}"))
        elif expr.startswith("env."):
            key = expr[len("env."):]
            return os.environ.get(key, f"{{{{env.{key}}}}}")
        return match.group(0)
    return re.sub(r"\{\{(.+?)\}\}", replacer, content)


# knowledge 传给 LLM 时固定使用空参数
KNOWLEDGE_PARAMETERS = {
    "type": "object",
    "properties": {},
    "required": []
}


class Tool:
    def __init__(self, name, meta, desc, func):
        self.name = name
        self.meta = meta
        self.desc = desc  # OpenAI tools 格式的 dict
        self.func = func


class Knowledge:
    def __init__(self, name, meta, desc, content):
        self.name = name
        self.meta = meta
        self.desc = desc  # OpenAI tools 格式的 dict
        self.content = content

    def render(self):
        return render_knowledge_content(self.content)


class Environment:
    def __init__(self, dir):
        dir = Path(dir)
        if (dir / "skills").is_dir():
            self.tools = load_tools_from_dir(dir / "skills")
        else:
            self.tools = load_tools_from_dir(dir / "tools")
        self.knowledges = load_knowledges_from_dir(dir / "knowledge")
        self.is_identity = dir.name == "skills"
        
    def get_tool(self, name):
        return self.tools[name]

    def get_knowledge(self, name):
        return self.knowledges[name]

    # def add_tool(self, meta):
        

def load_tool_from_dir(tool_dir, prefix=""):
    """从单个 tool 目录加载，返回 Tool 对象"""
    tool_dir = Path(tool_dir)
    if not tool_dir.is_dir():
        return None
    meta_file = tool_dir / "meta.json"
    if not meta_file.exists():
        # 兼容旧的 description.json
        meta_file = tool_dir / "description.json"
    if not meta_file.exists():
        print(f"WARNING: Tool {tool_dir} has no meta.json or description.json, skipping")
        return None
    meta = json.load(open(meta_file))

    # 从 meta 中提取 name（支持新旧两种格式）
    if "name" in meta:
        tool_name = meta["name"]
    elif "function" in meta:
        tool_name = meta["function"]["name"]
    else:
        print(f"WARNING: Tool {tool_dir} has no name field, skipping")
        return None

    # 加载脚本
    script_file = tool_dir / "scripts" / f"{tool_name}.py"
    func = None
    if script_file.exists():
        func = load_script(script_file, tool_name)
        if func is None:
            print(f"WARNING: Tool {tool_dir} script not found or function missing, skipping")
            return None

    # 组装 OpenAI tools 格式
    parameters = meta.get("parameters", meta.get("function", {}).get("parameters", {}))
    description = meta.get("description", meta.get("function", {}).get("description", ""))
    desc = {
        "type": "function",
        "function": {
            "name": prefix + tool_name,
            "description": description,
            "parameters": parameters,
        }
    }

    # 把 prefix 写入 meta 的 name 字段
    meta["name"] = prefix + tool_name

    return Tool(prefix + tool_name, meta, desc, func)


def load_knowledge_from_dir(knowledge_dir, prefix=""):
    """从单个 knowledge 目录加载，返回 Knowledge 对象"""
    knowledge_dir = Path(knowledge_dir)
    if not knowledge_dir.is_dir():
        return None
    meta_file = knowledge_dir / "meta.json"
    if not meta_file.exists():
        print(f"WARNING: Knowledge {knowledge_dir} has no meta.json, skipping")
        return None
    meta = json.load(open(meta_file))

    knowledge_name = meta.get("name", knowledge_dir.name)

    # 找 txt 文件作为知识内容
    txt_files = list(knowledge_dir.glob("*.txt"))
    if not txt_files:
        print(f"WARNING: Knowledge {knowledge_dir.name} has no .txt file, skipping")
        return None
    content = txt_files[0].read_text(encoding="utf-8")

    # 组装 OpenAI tools 格式（knowledge 固定用空参数）
    desc = {
        "type": "function",
        "function": {
            "name": prefix + knowledge_name,
            "description": meta.get("description", ""),
            "parameters": copy.deepcopy(KNOWLEDGE_PARAMETERS),
        }
    }

    # func 就是返回内容
    def knowledge_func():
        return content

    # 把 prefix 写入 meta 的 name 字段
    meta["name"] = prefix + knowledge_name

    return Knowledge(prefix + knowledge_name, meta, desc, content)


def load_tools_from_dir(tools_dir, prefix=""):
    """扫描 skills/tools 目录，加载所有 tool"""
    tools_dir = Path(tools_dir)
    if not tools_dir.exists() or not tools_dir.is_dir():
        return {}
    if not prefix:
        if tools_dir.name == "skills":
            base = f"IDENTITY<{tools_dir.parent.parent.resolve()}>:"
        else:
            base = f"ENV<{tools_dir.parent.resolve()}>:"
        prefix = base + "TOOL:"
    all_tools = {}
    for item in tools_dir.iterdir():
        if not item.is_dir():
            continue
        tool = load_tool_from_dir(item, prefix=prefix)
        if tool:
            all_tools[tool.name] = tool
    return all_tools


def load_knowledges_from_dir(knowledge_dir, prefix=""):
    """扫描 knowledge 目录，加载所有 knowledge"""
    knowledge_dir = Path(knowledge_dir)
    if not knowledge_dir.exists() or not knowledge_dir.is_dir():
        return {}
    if not prefix:
        if knowledge_dir.parent.name != ".environment":
            base = f"IDENTITY<{knowledge_dir.parent.parent.resolve()}>:"
        else:
            base = f"ENV<{knowledge_dir.parent.resolve()}>:"
        prefix = base + "KNOWLEDGE:"
    all_knowledge = {}
    for item in knowledge_dir.iterdir():
        if not item.is_dir():
            continue
        k = load_knowledge_from_dir(item, prefix=prefix)
        if k:
            all_knowledge[k.name] = k
    return all_knowledge

def load_environment_from_dir(base_dir):
    return Environment(base_dir)

if __name__ == "__main__":
    # 测试加载 tool
    tools = load_tools_from_dir(Path("/home/tiger/egoagent/identity/id1/ego/skills"))
    print("=== Tools ===")
    for name, tool in tools.items():
        print(f"  {name}: {tool.desc}")

    # 测试加载 knowledge
    knowledge = load_knowledges_from_dir(Path("/home/tiger/egoagent/identity/id1/ego/knowledge"))
    print("\n=== Knowledge ===")
    for name, k in knowledge.items():
        print(f"  {name}: {k.desc['function']['description'][:50]}...")
