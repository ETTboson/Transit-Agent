import json
import unittest

from agent.domain_context import DOMAIN_CONTEXT, context_prompt


class DomainContextTests(unittest.TestCase):
    def test_prompt_carries_serializable_context_without_losing_chinese(self):
        prompt = context_prompt()
        parsed = json.loads(prompt.split("Context：\n", 1)[1])
        self.assertEqual(parsed, DOMAIN_CONTEXT)
        self.assertIn("交通方式", prompt)
        self.assertIn("运行表现", prompt)

    def test_roles_define_input_fields_without_assigning_case_values(self):
        self.assertEqual(set(DOMAIN_CONTEXT["roles"]), {
            "ORIGIN", "DESTINATION", "EXTENT", "TIME", "MODE", "CONSTRAINT",
        })
        for role in DOMAIN_CONTEXT["roles"].values():
            self.assertEqual(set(role), {"label", "identify"})
        self.assertIn("不是当前任务的事实或默认参数", context_prompt())

    def test_performance_is_about_traffic_operation(self):
        performance = DOMAIN_CONTEXT["concepts"]["PERFORMANCE"]
        self.assertEqual(performance["label"], "运行表现")
        self.assertEqual(performance["examples"], ["旅行时间", "可靠性", "准点率", "拥挤度"])


if __name__ == "__main__":
    unittest.main()
