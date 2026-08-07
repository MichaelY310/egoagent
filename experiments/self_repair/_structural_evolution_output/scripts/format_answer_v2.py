def run(ctx):
    response = ctx['response']
    # Extract last numerical value using regex
    import re
    match = re.search(r'\b\d+\.?\d*\b', response)
    if match:
        answer = match.group(0)
        return {'response': f'<final_answer>{answer}</final_answer>'}
    return {'response': response}