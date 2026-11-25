"""Exercise the actual HTTP entry point without any provider calls."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import egoagent_server.server as server
from egoagent_core.flow_configuration import saved_flow_configuration
from harness_versions import ensure_harness_versions, snapshot_harness_version


class SavedFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.flow = self.root / "harness" / "demo"
        self.flow.mkdir(parents=True)
        self.config = {"name":"demo", "slots":{"agent":{"required":True,"identity":"test_bot"}},
                       "pipeline":{"start":"input","mode":"chat","nodes":{"input":{"op":"输入"},"model":{"op":"Agent","agent":"agent"}}}}
        self.write_config()
        self.v1 = ensure_harness_versions(self.flow)["latest"]
        self.patches = [patch.object(server,"HARNESS_DIR",self.flow.parent),
                        patch.object(server,"_project_portfolio"),
                        patch.object(server,"_workspace_security",return_value=({},{})),
                        patch.object(server.interactive_execution,"start")]
        for p in self.patches:
            p.start()
        server.interactive_execution.start.side_effect = lambda **kwargs: SimpleNamespace(
            run_id="test-only", snapshot=lambda: {key:kwargs[key] for key in ("mode","agents","harness_version","surface")})
        self.http = server.ThreadingHTTPServer(("127.0.0.1",0),server.APIHandler)
        self.thread = threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(timeout=3)
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def write_config(self):
        (self.flow / "config.json").write_text(json.dumps(self.config),encoding="utf-8")

    def start(self, **overrides):
        body = {"harness":"demo","harness_version":self.v1,"surface":"chat","workspace":str(self.root),**overrides}
        client = http.client.HTTPConnection("127.0.0.1", self.http.server_address[1], timeout=5)
        try:
            client.request("POST","/api/execution/start",json.dumps(body),{"Content-Type":"application/json"})
            response=client.getresponse()
            return response.status,json.loads(response.read())
        finally:
            client.close()

    def test_chat_ignores_all_legacy_overrides_and_keeps_manual_approval(self):
        status, result=self.start(agents={"agent":"identity/coder"},mode="evolve",mutation_targets=["all"])
        self.assertEqual(status,200,result)
        self.assertEqual(result["state"]["agents"],{"agent":"identity/test_bot"})
        self.assertEqual(result["state"]["mode"],"chat")
        args=server.interactive_execution.start.call_args.kwargs
        self.assertEqual(args["mutation_targets"],[])
        self.assertEqual(args["approval_mode"],"manual")
        self.assertEqual(args["security"]["defaults"]["write"],"deny")

    def test_builder_uses_the_same_saved_policy_as_chat(self):
        status,result=self.start(surface="builder",mode="agent",agents={"agent":"identity/coder"})
        self.assertEqual(status,200,result)
        self.assertEqual(result["state"]["mode"],"chat")
        self.assertEqual(result["state"]["agents"],{"agent":"identity/test_bot"})

    def test_version_pins_both_identity_and_policy(self):
        self.config["slots"]["agent"]["identity"]="deepseek_operator"
        self.config["pipeline"]["mode"]="plan"
        self.write_config()
        v2=snapshot_harness_version(self.flow)["id"]
        for version,identity,mode in [(self.v1,"test_bot","chat"),(v2,"deepseek_operator","plan"),("latest","deepseek_operator","plan")]:
            status,result=self.start(harness_version=version)
            self.assertEqual(status,200,result)
            self.assertEqual(result["state"]["agents"],{"agent":"identity/"+identity})
            self.assertEqual(result["state"]["mode"],mode)
        self.assertEqual(result["state"]["harness_version"],v2)

    def test_unbound_flow_is_rejected_before_worker_starts(self):
        del self.config["slots"]["agent"]["identity"]
        self.write_config()
        version=snapshot_harness_version(self.flow)["id"]
        status,result=self.start(harness_version=version,agents={"agent":"identity/test_bot"})
        self.assertEqual(status,400,result)
        self.assertIn("Build",str(result))
        server.interactive_execution.start.assert_not_called()

    def test_unknown_identity_is_rejected_synchronously(self):
        self.config["slots"]["agent"]["identity"]="no_such_identity_test"
        self.write_config()
        status,result=self.start(harness_version=snapshot_harness_version(self.flow)["id"])
        self.assertEqual(status,400,result)
        self.assertIn("不存在",str(result))
        server.interactive_execution.start.assert_not_called()

    def test_optional_unused_roles_and_non_model_flow(self):
        cfg=copy.deepcopy(self.config)
        cfg["slots"]={"optional":{"required":False}}
        cfg["pipeline"]["nodes"]={"input":{"op":"输入"}}
        self.assertEqual(saved_flow_configuration(cfg,"demo")["agents"],{})
        cfg["pipeline"]["nodes"]["model"]={"op":"Agent","agent":"undeclared"}
        with self.assertRaisesRegex(ValueError,"undeclared"):
            saved_flow_configuration(cfg,"demo")

    def test_evolution_targets_only_this_flow_and_its_bound_roles(self):
        self.config["pipeline"]["mode"]="evolve"
        self.config["slots"]["reviewer"]={"identity":"deepseek_operator"}
        self.write_config()
        status,result=self.start(harness_version=snapshot_harness_version(self.flow)["id"],mutation_targets=["all"])
        self.assertEqual(status,200,result)
        self.assertEqual(server.interactive_execution.start.call_args.kwargs["mutation_targets"],
                         ["deepseek_operator","demo","test_bot"])


if __name__ == "__main__":
    unittest.main()
