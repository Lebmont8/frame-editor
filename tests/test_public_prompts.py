import importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"public_prompts.py"
if not MODULE.exists(): MODULE=ROOT/"web/public_prompts.py"
spec=importlib.util.spec_from_file_location("public_prompts_contract",MODULE)
loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)

class PromptConfigurationTest(unittest.TestCase):
    def test_missing_file_configuration_fails_closed(self):
        with patch.dict(os.environ,{"PUBLIC_PROMPTS_FILE":""}):
            with self.assertRaises(RuntimeError):loader.required_prompt("customer")
    def test_empty_template_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"instructions.json";p.write_text(json.dumps({"customer":""}))
            with patch.dict(os.environ,{"PUBLIC_PROMPTS_FILE":str(p)}):
                with self.assertRaises(ValueError):loader.required_prompt("customer")
    def test_explicit_instructions_keep_context_as_serialized_data(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"instructions.json";p.write_text(json.dumps({"customer":"Synthetic test instruction."}))
            with patch.dict(os.environ,{"PUBLIC_PROMPTS_FILE":str(p)}):
                result=loader.required_prompt("customer",shop_name="Example",knowledge="quoted\\ninput")
            instruction,context=result.split("\n\n",1)
            self.assertEqual(instruction,"Synthetic test instruction.")
            self.assertEqual(json.loads(context),{"shop_name":"Example","knowledge":"quoted\\ninput"})
    def test_missing_key_never_uses_a_builtin_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"instructions.json";p.write_text("{}")
            with patch.dict(os.environ,{"PUBLIC_PROMPTS_FILE":str(p)}):
                with self.assertRaises(ValueError):loader.required_prompt("missing")
if __name__=="__main__":unittest.main()
