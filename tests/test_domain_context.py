import json
import unittest

from agent.domain_context import DOMAIN_CONTEXT, context_prompt
from agent.tools.catalog import ACTION_PROMPT, TOOL_HELP


class DomainContextTests(unittest.TestCase):
    def test_prompt_carries_complete_serializable_english_context(self):
        prompt = context_prompt()
        parsed = json.loads(prompt.split("Context:\n", 1)[1])
        self.assertEqual(parsed, DOMAIN_CONTEXT)
        self.assertEqual(set(parsed["concepts"]), {
            "TRANSPORT_MODE", "LOCATION", "NETWORK", "ROUTE", "SERVICE",
            "DEMAND", "SUPPLY", "PERFORMANCE", "EVENT",
        })
        self.assertNotRegex(prompt, r"[\u4e00-\u9fff]")

    def test_roles_define_input_fields_without_assigning_case_values(self):
        self.assertEqual(set(DOMAIN_CONTEXT["roles"]), {
            "ORIGIN", "DESTINATION", "EXTENT", "TIME", "MODE", "CONSTRAINT",
        })
        for role in DOMAIN_CONTEXT["roles"].values():
            self.assertEqual(set(role), {"label", "identify"})
        self.assertIn("not task facts or default parameters", context_prompt())

    def test_performance_is_about_traffic_operation(self):
        performance = DOMAIN_CONTEXT["concepts"]["PERFORMANCE"]
        self.assertEqual(performance["label"], "Operational performance")
        self.assertEqual(performance["examples"], ["travel time", "reliability", "punctuality", "crowding"])

    def test_tool_instructions_use_english_action_schema(self):
        action = json.loads(next(line for line in ACTION_PROMPT.splitlines() if line.startswith('{"action"')))
        self.assertEqual(set(action), {"action", "task", "tool", "params", "file_dependencies", "reason"})
        self.assertEqual(action["action"], "professional_tool")
        self.assertIn('{"result":"feed","path":["graph"]}', ACTION_PROMPT)
        self.assertNotRegex(ACTION_PROMPT + json.dumps(TOOL_HELP, ensure_ascii=False), r"[\u4e00-\u9fff]")


if __name__ == "__main__":
    unittest.main()
