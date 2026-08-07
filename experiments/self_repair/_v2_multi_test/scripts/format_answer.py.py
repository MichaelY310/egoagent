import re
def run(ctx):
    response = ctx['response']
    question = ctx['question']
    # Check if final answer tag exists
    if '<final_answer>' in response:
        return {'response': response}
    # Extract answer from \boxed{}, ####, or last line
    boxed_match = re.search(r'\boxed\{([^\}]+)\}', response)
    if boxed_match:
        answer = boxed_match.group(1).strip()
        return {'response': f'<final_answer>{answer}</final_answer>'}
    hash_match = re.search(r'####\s*([0-9,.]+)', response)
    if hash_match:
        answer = hash_match.group(1).strip()
        return {'response': f'<final_answer>{answer}</final_answer>'}
    # Check last line for number
    last_line = response.split('\n')[-1].strip()
    if last_line.isdigit() or (re.match(r'\d+\.?\d*', last_line)):
        answer = last_line
        return {'response': f'<final_answer>{answer}</final_answer>'}
    return {'response': response}