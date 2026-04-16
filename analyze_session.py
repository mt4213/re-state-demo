import argparse
import json
import sys

def main():
    parser = argparse.ArgumentParser(description="Analyze agent session telemetry from messages.json")
    parser.add_argument(
        "input_file",
        nargs="?",
        default="agent-core/state/messages.json",
        help="Path to the JSON state file (default: agent-core/state/messages.json)"
    )
    args = parser.parse_args()

    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            messages = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found at {args.input_file}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {args.input_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading {args.input_file}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(messages, list):
        print(f"Error: Expected top-level JSON structure to be an array in {args.input_file}", file=sys.stderr)
        sys.exit(1)

    total_messages = len(messages)
    assistant_turns = 0
    total_tool_calls = 0
    unique_tools_used = set()
    unique_files_read = set()
    stall_detected = False

    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            assistant_turns += 1
            tool_calls = msg.get("tool_calls", [])
            
            if tool_calls:
                total_tool_calls += len(tool_calls)
                
                for call in tool_calls:
                    function_data = call.get("function", call)
                    if isinstance(function_data, dict):
                        name = function_data.get("name")
                        
                        if name:
                            unique_tools_used.add(name)
                            
                        if name == "file_read":
                            args_str = function_data.get("arguments", "{}")
                            try:
                                args_obj = json.loads(args_str) if isinstance(args_str, str) else args_str
                                path = args_obj.get("path")
                                if path:
                                    unique_files_read.add(path)
                            except json.JSONDecodeError:
                                pass

    if messages and isinstance(messages[-1], dict):
        last_msg = messages[-1]
        if last_msg.get("role") == "assistant" and not last_msg.get("tool_calls"):
            stall_detected = True

    output = {
        "total_messages": total_messages,
        "assistant_turns": assistant_turns,
        "total_tool_calls": total_tool_calls,
        "unique_tools_used": list(unique_tools_used),
        "unique_files_read": list(unique_files_read),
        "stall_detected": stall_detected
    }

    print(json.dumps(output, indent=4))

if __name__ == "__main__":
    main()
