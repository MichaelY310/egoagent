import re
def run(ctx):
    response = ctx['response']
    question = ctx['question']
    # Check for \boxed{} format
    boxed_match = re.search(r'\boxed\{([^\}]+)\}', response)
    if boxed_match:
        return {'response': f'<final_answer>{boxed_match.group(1)}</final_answer>'}
    # Check for #### answer indicator
    sharp_match = re.search(r'####\s*(\d+)', response)
    if sharp_match:
        return {'response': f'<final_answer>{sharp_match.group(1)}</final_answer>'}
    # Check for number at end of response
    last_line_match = re.search(r'\d+\.?\d*$', response)
    if last_line_match:
        return {'response': f'<final_answer>{last_line_match.group(0)}</final_answer>'}
    # Fallback: extract first number
    numbers = re.findall(r'\d+\.?\d*', response)
    if numbers:
        return {'response': f'<final_answer>{numbers[0]}</final_answer>'}
    return {'response': response}