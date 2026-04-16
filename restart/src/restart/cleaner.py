import re

def clean_log(input_file, output_file, max_len=500):
    pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2}),\d{3}|\s{23})\s+([A-Z]+):\s+(.*)$')
    inner_prefix_pattern = re.compile(r'^(\[.*?\])\s+\[\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}\]\s+[A-Z]+\s+(.*)$')

    last_msg = None
    last_prefix = None
    consecutive_count = 0
    msg_counts = {}

    def flush_consecutive(f_out):
        nonlocal consecutive_count, last_msg, last_prefix
        if consecutive_count > 1:
            f_out.write(f"{last_prefix}[... previous line repeated {consecutive_count - 1} more times ...]\n")
        consecutive_count = 0

    with open(input_file, 'r', encoding='utf-8') as f_in, open(output_file, 'w', encoding='utf-8') as f_out:
        for line in f_in:
            original_line = line.rstrip('\n')
            match = pattern.match(original_line)

            prefix = ""
            msg = original_line

            if match:
                full_time_or_spaces = match.group(1)
                time_only = match.group(2)
                level = match.group(3)
                msg = match.group(4)
                
                if time_only:
                    prefix = f"{time_only} {level}: "
                else:
                    prefix = f"{' ' * 8} {level}: "
            else:
                msg = original_line

            inner_match = inner_prefix_pattern.match(msg)
            is_agent = False
            is_docker = False
            
            if inner_match:
                proc_name = inner_match.group(1)
                rest_of_msg = inner_match.group(2)
                msg = f"{proc_name} {rest_of_msg}"
                if proc_name == "[agent]":
                    is_agent = True
            elif msg.startswith("[docker]"):
                is_docker = True
            elif msg.startswith("[agent]"):
                is_agent = True

            if is_docker:
                msg_lower = msg.lower()
                if not any(kw in msg_lower for kw in ["error", "exception", "warn", "listening", "fail"]):
                    continue

            if len(msg) > max_len:
                msg = msg[:max_len] + "...[truncated]"

            norm_msg = re.sub(r'pid=\d+', 'pid=<PID>', msg)
            norm_msg = re.sub(r'in \d+\.\d+ seconds', 'in <SEC> seconds', norm_msg)
            norm_msg = re.sub(r'last runtime \d+\.\d+ s', 'last runtime <SEC> s', norm_msg)

            if norm_msg == last_msg:
                consecutive_count += 1
            else:
                flush_consecutive(f_out)
                if is_agent:
                    f_out.write(f"{prefix}{msg}\n")
                else:
                    msg_counts[norm_msg] = msg_counts.get(norm_msg, 0) + 1
                    if msg_counts[norm_msg] <= 3:
                        f_out.write(f"{prefix}{msg}\n")
                    elif msg_counts[norm_msg] == 4:
                        f_out.write(f"{prefix}{msg}  <-- [Subsequent identical events suppressed]\n")

                last_msg = norm_msg
                last_prefix = prefix
                consecutive_count = 1
        
        flush_consecutive(f_out)
