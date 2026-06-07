from pathlib import Path
import json
from llm.llm import Identity
import time

if __name__ == "__main__":
    identity_path = "/home/tiger/egoagent/identity/id1"
    identity = Identity(identity_path)
    llm = identity.get_llm()
    system_prompt = identity.ID.get("system_prompt", "")
    messages = [{"role": "system", "content": system_prompt}]

    # 获取所有 tools 的 desc 列表（传给 LLM）
    tools_desc = [t.desc for t in identity.EGO.tools.values()]
    tools_desc += [k.desc for k in identity.EGO.knowledges.values()]

    prompt = ""
    # 用户交互loop
    while True:
        prompt = input(">>> ")
        if prompt == "exit":
            break
        messages.append({"role": "user", "content": prompt})

        # ReAct loop
        while True:
            response = ""
            tool_calls = []
            for delta in llm.chat_stream(messages, tools=tools_desc):
                content = delta.get("content", "")
                if content:
                    print(content, end="", flush=True)
                    response += content

                if delta.get("tool_calls"):
                    tool_calls = delta["tool_calls"]
                    print("<tool_calls>")
                    print("tool calls: ", tool_calls)
                    print("</tool_calls>")

            print()

            if tool_calls:
                messages.append({"role": "assistant", "content": response, "tool_calls": tool_calls})
            else:
                messages.append({"role": "assistant", "content": response})

            if not tool_calls:
                break

            print("<tool_results>")
            for tool_call in tool_calls:
                print("<tool_result>")
                tool_name = tool_call["function"]["name"]
                if tool_name in identity.EGO.tools:
                    tool = identity.EGO.tools[tool_name]
                    arguments = json.loads(tool_call["function"]["arguments"])
                    try:
                        result = tool.func(**arguments)
                        print(f"Tool {tool_name} result: {result}")
                    except Exception as e:
                        result = f"Tool {tool_name} error: {str(e)}"
                        print(f"ERROR: Tool {tool_name} error: {str(e)}")
                elif tool_name in identity.EGO.knowledges:
                    result = identity.EGO.knowledges[tool_name].content
                    print(f"Knowledge {tool_name} returned")
                else:
                    result = f"Tool not found: {tool_name}"
                    print(f"ERROR: Tool not found: {tool_name}")
                print("</tool_result>")
                messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": result
                    })
            print("</tool_results>")
        
    with open(f"chat_react_{time.strftime('%Y%m%d_%H%M%S', time.localtime())}.log", "w") as f:
        f.write(json.dumps(messages, ensure_ascii=False, indent=2))
