"""
Meilisearch Manager - 管理 tool 和 knowledge 的搜索索引

主要功能：
- 启动/停止 Meilisearch 服务进程
- 索引 tool 和 knowledge（分开管理）
- 搜索 tool 和 knowledge
- 清空索引

使用方式：
    from meilisearch_manager import MeilisearchManager
    
    mgr = MeilisearchManager(port=7700)
    mgr.start()                          # 启动 meilisearch 服务
    mgr.index_tools(agent.tools)         # 索引所有 tool
    mgr.index_knowledges(agent.knowledges)  # 索引所有 knowledge
    results = mgr.search_tools("文件编辑")   # 搜索 tool
    results = mgr.search_knowledges("配置")  # 搜索 knowledge
    results = mgr.search_all("文件")         # 搜索 tool + knowledge
    mgr.clear()                          # 清空所有索引
    mgr.stop()                           # 停止服务
"""

import os
import time
import json
import signal
import subprocess
import socket
from pathlib import Path

import meilisearch


# Meilisearch 二进制路径
MEILISEARCH_BIN = "/home/tiger/egoagent/meilisearch/target/release/meilisearch"

# 索引名称
TOOLS_INDEX = "tools"
KNOWLEDGE_INDEX = "knowledges"


def _find_free_port():
    """找一个可用端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _wait_for_port(port, timeout=15):
    """等待端口可连接"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    return False


class MeilisearchManager:
    def __init__(self, port=None, master_key=""):
        """
        Args:
            port: 服务端口，None 则自动找一个空闲端口
            master_key: Meilisearch master key（空字符串表示无认证）
        """
        self.port = port or _find_free_port()
        self.master_key = master_key
        self.url = f"http://127.0.0.1:{self.port}"
        self.process = None
        self.client = None
        self._db_path = None

    def _kill_existing_on_port(self):
        """杀掉残留在同一端口的旧 Meilisearch 进程"""
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{self.port}"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                for pid_str in result.stdout.strip().split("\n"):
                    pid = int(pid_str.strip())
                    os.kill(pid, signal.SIGKILL)
                time.sleep(0.5)
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, ProcessLookupError):
            pass

    def start(self):
        """启动 Meilisearch 服务进程"""
        if self.process and self.process.poll() is None:
            print(f"[MeilisearchManager] 服务已在运行 (port={self.port}, pid={self.process.pid})")
            return

        # 确保 localhost 请求不走代理
        os.environ.setdefault("no_proxy", "")
        if "127.0.0.1" not in os.environ["no_proxy"]:
            os.environ["no_proxy"] = os.environ["no_proxy"] + ",127.0.0.1,localhost"

        if not os.path.isfile(MEILISEARCH_BIN):
            raise FileNotFoundError(f"Meilisearch 二进制不存在: {MEILISEARCH_BIN}")

        # 杀掉可能残留在同一端口的旧进程
        self._kill_existing_on_port()

        # 使用临时目录存储数据（每次启动清空，确保干净状态）
        self._db_path = f"/tmp/meilisearch_egoagent_{self.port}"
        if os.path.exists(self._db_path):
            import shutil
            shutil.rmtree(self._db_path, ignore_errors=True)
        os.makedirs(self._db_path, exist_ok=True)

        cmd = [
            MEILISEARCH_BIN,
            "--http-addr", f"127.0.0.1:{self.port}",
            "--db-path", self._db_path,
            "--env", "development",
            "--no-analytics",
        ]
        if self.master_key:
            cmd += ["--master-key", self.master_key]

        # 启动进程
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid,  # 新进程组，方便后续清理
        )

        # 等待服务就绪
        if not _wait_for_port(self.port, timeout=15):
            self.process.kill()
            raise RuntimeError(f"Meilisearch 启动超时 (port={self.port})")

        # 等待服务完全初始化（端口就绪不代表 API 可用）
        self.client = meilisearch.Client(self.url, self.master_key or None)
        self._wait_for_api_ready()

        # 创建索引并配置
        self._setup_indexes()

        print(f"[MeilisearchManager] 服务已启动 (port={self.port}, pid={self.process.pid})")

    def _wait_for_api_ready(self, timeout=15):
        """等待 Meilisearch API 完全可用（health 端点返回正常）"""
        import urllib.request
        start = time.time()
        while time.time() - start < timeout:
            try:
                req = urllib.request.Request(f"{self.url}/health")
                resp = urllib.request.urlopen(req, timeout=2)
                if resp.status == 200:
                    return
            except:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"Meilisearch API 未就绪 (port={self.port})")

    def _setup_indexes(self):
        """创建 tools 和 knowledges 索引，配置搜索属性"""
        # Tools 索引
        task = self.client.create_index(TOOLS_INDEX, {"primaryKey": "id"})
        self.client.wait_for_task(task.task_uid)
        tools_index = self.client.index(TOOLS_INDEX)
        task = tools_index.update_settings({
            "searchableAttributes": ["name", "short_name", "description", "tags"],
            "filterableAttributes": ["type", "source"],
            "sortableAttributes": ["name"],
            "rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"],
        })
        self.client.wait_for_task(task.task_uid)

        # Knowledge 索引
        task = self.client.create_index(KNOWLEDGE_INDEX, {"primaryKey": "id"})
        self.client.wait_for_task(task.task_uid)
        knowledge_index = self.client.index(KNOWLEDGE_INDEX)
        task = knowledge_index.update_settings({
            "searchableAttributes": ["name", "short_name", "description", "content_preview", "tags"],
            "filterableAttributes": ["type", "source"],
            "sortableAttributes": ["name"],
            "rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"],
        })
        self.client.wait_for_task(task.task_uid)

    def stop(self):
        """停止 Meilisearch 服务"""
        if self.process and self.process.poll() is None:
            os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
            print(f"[MeilisearchManager] 服务已停止 (port={self.port})")
        self.process = None
        self.client = None

        # 清理临时数据目录
        if self._db_path and os.path.exists(self._db_path):
            import shutil
            shutil.rmtree(self._db_path, ignore_errors=True)

    def index_tools(self, tools_dict):
        """
        将 agent 的 tools 字典索引到 Meilisearch
        
        Args:
            tools_dict: {full_name: Tool} 字典，和 agent.tools 格式一致
        """
        if not self.client:
            raise RuntimeError("Meilisearch 未启动，请先调用 start()")

        documents = []
        for full_name, tool in tools_dict.items():
            # 提取短名字
            short_name = full_name.split(":")[-1] if ":" in full_name else full_name
            # 提取来源
            source = ""
            if "IDENTITY<" in full_name:
                source = "identity"
            elif "ENV<" in full_name:
                source = "environment"

            desc = tool.desc.get("function", {})
            doc = {
                "id": full_name.replace("/", "_").replace("<", "_").replace(">", "_").replace(":", "_"),
                "full_name": full_name,
                "name": desc.get("name", short_name),
                "short_name": short_name,
                "description": desc.get("description", ""),
                "parameters": json.dumps(desc.get("parameters", {}), ensure_ascii=False),
                "tags": tool.meta.get("tags", []),
                "type": "tool",
                "source": source,
            }
            documents.append(doc)

        if documents:
            index = self.client.index(TOOLS_INDEX)
            task = index.add_documents(documents)
            self.client.wait_for_task(task.task_uid)
            print(f"[MeilisearchManager] 索引了 {len(documents)} 个 tool")

    def index_knowledges(self, knowledges_dict):
        """
        将 agent 的 knowledges 字典索引到 Meilisearch
        
        Args:
            knowledges_dict: {full_name: Knowledge} 字典，和 agent.knowledges 格式一致
        """
        if not self.client:
            raise RuntimeError("Meilisearch 未启动，请先调用 start()")

        documents = []
        for full_name, knowledge in knowledges_dict.items():
            short_name = full_name.split(":")[-1] if ":" in full_name else full_name
            source = ""
            if "IDENTITY<" in full_name:
                source = "identity"
            elif "ENV<" in full_name:
                source = "environment"

            desc = knowledge.desc.get("function", {})
            # 内容预览（前500字用于搜索）
            content_preview = knowledge.content[:500] if knowledge.content else ""

            doc = {
                "id": full_name.replace("/", "_").replace("<", "_").replace(">", "_").replace(":", "_"),
                "full_name": full_name,
                "name": desc.get("name", short_name),
                "short_name": short_name,
                "description": desc.get("description", ""),
                "content_preview": content_preview,
                "tags": knowledge.meta.get("tags", []),
                "type": "knowledge",
                "source": source,
            }
            documents.append(doc)

        if documents:
            index = self.client.index(KNOWLEDGE_INDEX)
            task = index.add_documents(documents)
            self.client.wait_for_task(task.task_uid)
            print(f"[MeilisearchManager] 索引了 {len(documents)} 个 knowledge")

    def remove_tool(self, full_name):
        """删除单个 tool"""
        if not self.client:
            return
        doc_id = full_name.replace("/", "_").replace("<", "_").replace(">", "_").replace(":", "_")
        index = self.client.index(TOOLS_INDEX)
        task = index.delete_document(doc_id)
        self.client.wait_for_task(task.task_uid)

    def remove_knowledge(self, full_name):
        """删除单个 knowledge"""
        if not self.client:
            return
        doc_id = full_name.replace("/", "_").replace("<", "_").replace(">", "_").replace(":", "_")
        index = self.client.index(KNOWLEDGE_INDEX)
        task = index.delete_document(doc_id)
        self.client.wait_for_task(task.task_uid)

    def clear(self):
        """清空所有索引"""
        if not self.client:
            return
        task = self.client.index(TOOLS_INDEX).delete_all_documents()
        self.client.wait_for_task(task.task_uid)
        task = self.client.index(KNOWLEDGE_INDEX).delete_all_documents()
        self.client.wait_for_task(task.task_uid)
        print("[MeilisearchManager] 已清空所有索引")

    def search_tools(self, query, limit=10):
        """
        搜索 tool
        
        Args:
            query: 搜索关键词
            limit: 最多返回条数
            
        Returns:
            list of dict: [{full_name, short_name, description, parameters}, ...]
        """
        if not self.client:
            return []
        index = self.client.index(TOOLS_INDEX)
        results = index.search(query, {"limit": limit})
        return [
            {
                "full_name": hit["full_name"],
                "short_name": hit["short_name"],
                "description": hit["description"],
                "parameters": hit.get("parameters", "{}"),
            }
            for hit in results["hits"]
        ]

    def search_knowledges(self, query, limit=10):
        """
        搜索 knowledge
        
        Args:
            query: 搜索关键词
            limit: 最多返回条数
            
        Returns:
            list of dict: [{full_name, short_name, description, content_preview}, ...]
        """
        if not self.client:
            return []
        index = self.client.index(KNOWLEDGE_INDEX)
        results = index.search(query, {"limit": limit})
        return [
            {
                "full_name": hit["full_name"],
                "short_name": hit["short_name"],
                "description": hit["description"],
                "content_preview": hit.get("content_preview", "")[:200],
            }
            for hit in results["hits"]
        ]

    def search_all(self, query, limit=10):
        """
        同时搜索 tool 和 knowledge
        
        Returns:
            dict: {"tools": [...], "knowledges": [...]}
        """
        return {
            "tools": self.search_tools(query, limit=limit),
            "knowledges": self.search_knowledges(query, limit=limit),
        }

    @property
    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def __del__(self):
        """析构时确保停止服务"""
        try:
            self.stop()
        except:
            pass
