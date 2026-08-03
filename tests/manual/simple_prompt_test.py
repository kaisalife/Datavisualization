
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from prompts.agent_prompt import get_agent_chart_designer_prompt

print("Testing prompt template...")
prompt = get_agent_chart_designer_prompt()

print("Prompt template variables:", prompt.input_variables)

# Test with the same variables as in the main code
test_input = {
    "data_file_path": "test.xls",
    "data_preview": "test preview",
    "user_prompt": "test prompt",
    "mcp_prompt": "",
    "skill_prompt": ""
}

print("\nTesting with input variables:", list(test_input.keys()))

try:
    formatted_prompt = prompt.format(**test_input)
    print("✅ Success! Prompt formatted without errors.")
    print("\nFormatted prompt (first 500 chars):")
    print(formatted_prompt[:500])
except KeyError as e:
    print(f"❌ KeyError: {e}")
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

