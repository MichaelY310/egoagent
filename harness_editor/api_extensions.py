"""
EgoAgent Extended API - Backend endpoints for Void IDE integration.
Provides: Experiment Management, Environment Management, Multi-Agent Coordination,
         Skill/Tool Browser, and Pipeline Execution Tracking.
"""

import json
import os
import sys
import time
import uuid
import threading
import traceback
from pathlib import Path
from typing import Dict, List, Any, Optional

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = PROJECT_ROOT / "harness"
IDENTITY_DIR = PROJECT_ROOT / "identity"
ENVIRONMENT_DIR = PROJECT_ROOT / "environment"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"

# ==================== Environment Management ====================

def list_environments() -> List[Dict]:
    """List all available environments with their tools/skills."""
    envs = []
    if not ENVIRONMENT_DIR.exists():
        return envs
    for env_dir in sorted(ENVIRONMENT_DIR.iterdir()):
        if env_dir.is_dir() and (env_dir / "config.json").exists():
            config = json.loads((env_dir / "config.json").read_text())
            tools = []
            tools_dir = env_dir / "tools"
            if tools_dir.exists():
                for tool_dir in tools_dir.iterdir():
                    if tool_dir.is_dir() and (tool_dir / "meta.json").exists():
                        meta = json.loads((tool_dir / "meta.json").read_text())
                        tools.append({
                            "name": meta.get("name", tool_dir.name),
                            "description": meta.get("description", ""),
                        })
            envs.append({
                "id": env_dir.name,
                "name": config.get("name", env_dir.name),
                "description": config.get("description", ""),
                "tools": tools,
                "tool_count": len(tools),
            })
    return envs


def create_environment(name: str, description: str = "", base_env: str = None) -> Dict:
    """Create a new environment, optionally based on an existing one."""
    env_dir = ENVIRONMENT_DIR / name
    if env_dir.exists():
        return {"error": f"Environment '{name}' already exists"}
    
    env_dir.mkdir(parents=True)
    (env_dir / "tools").mkdir()
    
    config = {"name": name, "description": description}
    
    if base_env:
        base_dir = ENVIRONMENT_DIR / base_env
        if base_dir.exists() and (base_dir / "config.json").exists():
            base_config = json.loads((base_dir / "config.json").read_text())
            config["based_on"] = base_env
            # Copy tools from base
            base_tools = base_dir / "tools"
            if base_tools.exists():
                import shutil
                shutil.copytree(str(base_tools), str(env_dir / "tools"), dirs_exist_ok=True)
    
    (env_dir / "config.json").write_text(json.dumps(config, indent=2))
    return {"id": name, "name": name, "description": description, "status": "created"}


def get_environment_for_workspace(workspace_path: str) -> Dict:
    """Auto-detect or create environment for a workspace folder."""
    ws = Path(workspace_path)
    env_config_path = ws / ".egoagent" / "environment.json"
    
    if env_config_path.exists():
        return json.loads(env_config_path.read_text())
    
    # Auto-detect based on project files
    detected = {"environments": [], "skills": []}
    
    if (ws / "package.json").exists():
        detected["environments"].append("nodejs")
        detected["skills"].extend(["npm_run", "file_edit", "terminal"])
    if (ws / "requirements.txt").exists() or (ws / "setup.py").exists() or (ws / "pyproject.toml").exists():
        detected["environments"].append("python")
        detected["skills"].extend(["pip_install", "pytest", "file_edit", "terminal"])
    if (ws / "Cargo.toml").exists():
        detected["environments"].append("rust")
        detected["skills"].extend(["cargo", "file_edit", "terminal"])
    if (ws / "go.mod").exists():
        detected["environments"].append("go")
        detected["skills"].extend(["go_build", "file_edit", "terminal"])
    if (ws / ".git").exists():
        detected["skills"].append("git")
    if (ws / "Dockerfile").exists() or (ws / "docker-compose.yml").exists():
        detected["skills"].append("docker")
    
    # Default fallback
    if not detected["environments"]:
        detected["environments"] = ["general"]
        detected["skills"] = ["file_edit", "terminal", "search"]
    
    return detected


def save_workspace_environment(workspace_path: str, config: Dict) -> Dict:
    """Save environment configuration for a workspace."""
    ws = Path(workspace_path)
    ego_dir = ws / ".egoagent"
    ego_dir.mkdir(parents=True, exist_ok=True)
    (ego_dir / "environment.json").write_text(json.dumps(config, indent=2))
    return {"status": "saved", "path": str(ego_dir / "environment.json")}


# ==================== Skill/Tool Browser ====================

def list_identity_skills(identity_name: str) -> Dict:
    """List all skills/tools available to a given identity."""
    identity_dir = IDENTITY_DIR / identity_name
    if not identity_dir.exists():
        return {"error": f"Identity '{identity_name}' not found"}
    
    skills = []
    ego_skills = identity_dir / "ego" / "skills"
    if ego_skills.exists():
        for skill_dir in sorted(ego_skills.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "meta.json").exists():
                meta = json.loads((skill_dir / "meta.json").read_text())
                scripts = []
                scripts_dir = skill_dir / "scripts"
                if scripts_dir.exists():
                    scripts = [f.stem for f in scripts_dir.glob("*.py")]
                skills.append({
                    "name": meta.get("name", skill_dir.name),
                    "description": meta.get("description", ""),
                    "parameters": meta.get("parameters", {}),
                    "scripts": scripts,
                })
    
    # Check superego hooks
    hooks = {}
    superego_dir = identity_dir / "superego"
    if superego_dir.exists():
        for hook_name in ["pre_llm_hook", "post_llm_hook", "pre_tool_hook", "post_tool_hook"]:
            hook_file = superego_dir / f"{hook_name}.py"
            if hook_file.exists():
                hooks[hook_name] = True
    
    # Knowledge bases
    knowledge = []
    knowledge_dir = identity_dir / "ego" / "knowledge"
    if knowledge_dir.exists():
        for kb_dir in knowledge_dir.iterdir():
            if kb_dir.is_dir() and (kb_dir / "meta.json").exists():
                meta = json.loads((kb_dir / "meta.json").read_text())
                knowledge.append({
                    "name": meta.get("name", kb_dir.name),
                    "description": meta.get("description", ""),
                })
    
    # Identity meta
    id_json = identity_dir / "id.json"
    meta = json.loads(id_json.read_text()) if id_json.exists() else {}
    
    return {
        "identity": identity_name,
        "display_name": meta.get("name", identity_name),
        "description": meta.get("description", ""),
        "model": meta.get("model", ""),
        "skills": skills,
        "skill_count": len(skills),
        "hooks": hooks,
        "knowledge": knowledge,
    }


def list_all_identities() -> List[Dict]:
    """List all available identities with summary."""
    identities = []
    if not IDENTITY_DIR.exists():
        return identities
    for id_dir in sorted(IDENTITY_DIR.iterdir()):
        if id_dir.is_dir():
            id_json = id_dir / "id.json"
            meta = json.loads(id_json.read_text()) if id_json.exists() else {}
            skill_count = 0
            ego_skills = id_dir / "ego" / "skills"
            if ego_skills.exists():
                skill_count = sum(1 for d in ego_skills.iterdir() if d.is_dir())
            identities.append({
                "id": id_dir.name,
                "name": meta.get("name", id_dir.name),
                "description": meta.get("description", ""),
                "model": meta.get("model", ""),
                "skill_count": skill_count,
            })
    return identities


# ==================== Experiment Management ====================

# In-memory experiment tracking
_experiments: Dict[str, Dict] = {}

def list_experiment_scenarios() -> List[Dict]:
    """List available experiment scenarios."""
    scenarios = []
    
    # V2 multi-scenario test scenarios
    v2_dir = EXPERIMENTS_DIR / "self_repair"
    if v2_dir.exists():
        scenarios.append({
            "id": "v2_multi_scenario",
            "name": "V2 Multi-Scenario Test",
            "description": "Tests DAG self-evolution on synthetic failure scenarios (format_missing, boxed_format, multi_step_extraction)",
            "script": str(v2_dir / "run_multi_scenario_test.py"),
            "params": {
                "scenarios": ["format_missing", "boxed_format_mismatch", "multi_step_extraction", "unit_conversion"],
                "max_iterations": {"type": "int", "default": 5, "min": 1, "max": 20},
                "questions_per_scenario": {"type": "int", "default": 5, "min": 1, "max": 50},
            }
        })
        scenarios.append({
            "id": "gsm8k_evolution",
            "name": "GSM8K Evolution Test",
            "description": "Tests evolution on real GSM8K math problems (phase1: evolve, phase2: generalize)",
            "script": str(v2_dir / "run_gsm8k_only.py"),
            "params": {
                "evolve_count": {"type": "int", "default": 20, "min": 5, "max": 100},
                "test_count": {"type": "int", "default": 30, "min": 10, "max": 200},
                "max_iterations": {"type": "int", "default": 5, "min": 1, "max": 20},
            }
        })
    
    # Generic evolution experiment
    scenarios.append({
        "id": "custom_evolution",
        "name": "Custom Evolution Experiment",
        "description": "Run V2 structural evolution on a custom harness with custom data",
        "params": {
            "harness": {"type": "select", "options": [], "default": "react_single"},
            "identity": {"type": "select", "options": [], "default": "dante"},
            "data_path": {"type": "string", "default": ""},
            "max_iterations": {"type": "int", "default": 5, "min": 1, "max": 20},
            "mode": {"type": "select", "options": ["v2_structural", "prompt_only", "full"], "default": "v2_structural"},
        }
    })
    
    return scenarios


def start_experiment(scenario_id: str, params: Dict) -> Dict:
    """Start an experiment asynchronously."""
    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
    
    experiment = {
        "id": exp_id,
        "scenario_id": scenario_id,
        "params": params,
        "status": "running",
        "started_at": time.time(),
        "progress": [],
        "result": None,
        "error": None,
    }
    _experiments[exp_id] = experiment
    
    def run_experiment():
        try:
            if scenario_id == "v2_multi_scenario":
                _run_v2_multi_scenario(exp_id, params)
            elif scenario_id == "gsm8k_evolution":
                _run_gsm8k_experiment(exp_id, params)
            elif scenario_id == "custom_evolution":
                _run_custom_evolution(exp_id, params)
            else:
                experiment["status"] = "error"
                experiment["error"] = f"Unknown scenario: {scenario_id}"
        except Exception as e:
            experiment["status"] = "error"
            experiment["error"] = str(e)
            experiment["traceback"] = traceback.format_exc()
    
    thread = threading.Thread(target=run_experiment, daemon=True)
    thread.start()
    
    return {"experiment_id": exp_id, "status": "started"}


def get_experiment_status(exp_id: str) -> Dict:
    """Get current experiment status and progress."""
    if exp_id not in _experiments:
        return {"error": f"Experiment '{exp_id}' not found"}
    return _experiments[exp_id]


def list_experiments() -> List[Dict]:
    """List all experiments (active and completed)."""
    # In-memory experiments
    results = list(_experiments.values())
    
    # Also scan saved experiment results
    results_dir = EXPERIMENTS_DIR / "self_repair" / "_v2_multi_test"
    if results_dir.exists():
        for f in sorted(results_dir.glob("*.json"), reverse=True)[:20]:
            try:
                data = json.loads(f.read_text())
                results.append({
                    "id": f.stem,
                    "scenario_id": "saved",
                    "status": "completed",
                    "started_at": os.path.getmtime(str(f)),
                    "result": data,
                    "source": "file",
                    "file_path": str(f),
                })
            except:
                pass
    
    return sorted(results, key=lambda x: x.get("started_at", 0), reverse=True)


def _run_v2_multi_scenario(exp_id: str, params: Dict):
    """Run V2 multi-scenario test."""
    experiment = _experiments[exp_id]
    
    sys.path.insert(0, str(EXPERIMENTS_DIR / "self_repair"))
    try:
        from run_multi_scenario_test import run_multi_scenario_test, SCENARIOS
    except ImportError:
        experiment["status"] = "error"
        experiment["error"] = "Cannot import run_multi_scenario_test"
        return
    
    selected = params.get("scenarios", list(SCENARIOS.keys()))
    max_iter = params.get("max_iterations", 5)
    q_count = params.get("questions_per_scenario", 5)
    
    all_results = {}
    for i, scenario_name in enumerate(selected):
        experiment["progress"].append({
            "step": f"Running scenario {i+1}/{len(selected)}: {scenario_name}",
            "time": time.time(),
        })
        
        try:
            result = run_multi_scenario_test(
                scenarios=[scenario_name],
                max_iterations=max_iter,
                questions_per_scenario=q_count,
            )
            all_results[scenario_name] = result.get(scenario_name, {})
        except Exception as e:
            all_results[scenario_name] = {"error": str(e)}
    
    experiment["status"] = "completed"
    experiment["result"] = all_results
    experiment["completed_at"] = time.time()
    
    # Save to file
    results_dir = EXPERIMENTS_DIR / "self_repair" / "_v2_multi_test"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    result_file = results_dir / f"exp_{timestamp}.json"
    result_file.write_text(json.dumps({
        "experiment_id": exp_id,
        "params": params,
        "results": all_results,
        "timestamp": timestamp,
    }, indent=2, ensure_ascii=False))


def _run_gsm8k_experiment(exp_id: str, params: Dict):
    """Run GSM8K evolution experiment."""
    experiment = _experiments[exp_id]
    experiment["progress"].append({"step": "Loading GSM8K data...", "time": time.time()})
    
    sys.path.insert(0, str(EXPERIMENTS_DIR / "self_repair"))
    try:
        from run_gsm8k_only import run_gsm8k_test
        result = run_gsm8k_test(
            evolve_count=params.get("evolve_count", 20),
            test_count=params.get("test_count", 30),
            max_iterations=params.get("max_iterations", 5),
        )
        experiment["status"] = "completed"
        experiment["result"] = result
    except Exception as e:
        experiment["status"] = "error"
        experiment["error"] = str(e)
        experiment["traceback"] = traceback.format_exc()
    
    experiment["completed_at"] = time.time()


def _run_custom_evolution(exp_id: str, params: Dict):
    """Run custom evolution experiment."""
    experiment = _experiments[exp_id]
    experiment["progress"].append({"step": "Starting custom evolution...", "time": time.time()})
    
    # This would call the V2 evolution engine with custom params
    experiment["status"] = "completed"
    experiment["result"] = {"message": "Custom evolution placeholder - implement per harness"}
    experiment["completed_at"] = time.time()


# ==================== Multi-Agent Pipeline Status ====================

# Active pipeline sessions
_active_sessions: Dict[str, Dict] = {}

def register_pipeline_session(session_id: str, harness_name: str, config: Dict) -> Dict:
    """Register a new pipeline execution session for tracking."""
    session = {
        "id": session_id,
        "harness": harness_name,
        "config": config,
        "started_at": time.time(),
        "status": "running",
        "current_node": config.get("pipeline", {}).get("start", ""),
        "node_history": [],
        "agents": {},
        "messages": [],
    }
    _active_sessions[session_id] = session
    return session


def update_pipeline_state(session_id: str, node_id: str, state: str, data: Dict = None) -> Dict:
    """Update pipeline node state (called during execution)."""
    if session_id not in _active_sessions:
        return {"error": "Session not found"}
    
    session = _active_sessions[session_id]
    session["current_node"] = node_id
    session["node_history"].append({
        "node": node_id,
        "state": state,  # "entering", "executing", "completed", "error"
        "time": time.time(),
        "data": data or {},
    })
    return {"status": "updated"}


def get_pipeline_state(session_id: str) -> Dict:
    """Get current pipeline execution state."""
    if session_id not in _active_sessions:
        return {"error": "Session not found"}
    return _active_sessions[session_id]


def list_active_sessions() -> List[Dict]:
    """List all active pipeline sessions."""
    return [
        {
            "id": s["id"],
            "harness": s["harness"],
            "status": s["status"],
            "current_node": s["current_node"],
            "started_at": s["started_at"],
            "step_count": len(s["node_history"]),
        }
        for s in _active_sessions.values()
    ]


# ==================== Harness Management (extended) ====================

def list_harnesses_with_details() -> List[Dict]:
    """List all harnesses with full details."""
    harnesses = []
    if not HARNESS_DIR.exists():
        return harnesses
    for h_dir in sorted(HARNESS_DIR.iterdir()):
        if h_dir.is_dir() and (h_dir / "config.json").exists():
            try:
                config = json.loads((h_dir / "config.json").read_text())
                pipeline = config.get("pipeline", {})
                nodes = pipeline.get("nodes", {})
                slots = config.get("slots", {})
                
                harnesses.append({
                    "id": h_dir.name,
                    "name": config.get("name", h_dir.name),
                    "description": config.get("description", ""),
                    "node_count": len(nodes),
                    "agent_count": len(slots),
                    "slots": list(slots.keys()),
                    "start_node": pipeline.get("start", ""),
                    "has_scripts": (h_dir / "scripts").exists(),
                    "has_protocol": (h_dir / "protocol.py").exists(),
                })
            except:
                pass
    return harnesses


# ==================== API Route Handler ====================

def handle_api_request(method: str, path: str, body: Dict = None) -> tuple:
    """
    Handle extended API requests. Returns (response_dict, status_code).
    Returns (None, None) if the path is not handled by this module.
    """
    body = body or {}
    
    # Environment APIs
    if method == "GET" and path == "/api/environments":
        return list_environments(), 200
    
    if method == "POST" and path == "/api/environments":
        return create_environment(
            name=body.get("name", ""),
            description=body.get("description", ""),
            base_env=body.get("base_env"),
        ), 200
    
    if method == "POST" and path == "/api/environments/detect":
        return get_environment_for_workspace(body.get("workspace", "")), 200
    
    if method == "POST" and path == "/api/environments/save":
        return save_workspace_environment(
            workspace_path=body.get("workspace", ""),
            config=body.get("config", {}),
        ), 200
    
    # Identity/Skill APIs
    if method == "GET" and path == "/api/identities":
        return list_all_identities(), 200
    
    if method == "GET" and path.startswith("/api/identity/") and path.endswith("/skills"):
        identity_name = path.split("/")[3]
        return list_identity_skills(identity_name), 200
    
    # Experiment APIs
    if method == "GET" and path == "/api/experiments/scenarios":
        return list_experiment_scenarios(), 200
    
    if method == "GET" and path == "/api/experiments":
        return list_experiments(), 200
    
    if method == "POST" and path == "/api/experiments/start":
        return start_experiment(
            scenario_id=body.get("scenario_id", ""),
            params=body.get("params", {}),
        ), 200
    
    if method == "GET" and path.startswith("/api/experiments/"):
        exp_id = path.split("/")[-1]
        return get_experiment_status(exp_id), 200
    
    # Pipeline status APIs
    if method == "GET" and path == "/api/pipeline/sessions":
        return list_active_sessions(), 200
    
    if method == "GET" and path.startswith("/api/pipeline/session/"):
        session_id = path.split("/")[-1]
        return get_pipeline_state(session_id), 200
    
    # Harness APIs (extended)
    if method == "GET" and path == "/api/harnesses/detailed":
        return list_harnesses_with_details(), 200
    
    # Not handled
    return None, None
