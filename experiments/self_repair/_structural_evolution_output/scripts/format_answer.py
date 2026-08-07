def run(ctx):
    response = ctx['response']
    import re
    match = re.search(r'\b(\d+)\b', response)
    if match:
        formatted = f'<final_answer>{match.group(1)}</final_answer>'
        return {'response': response + '\n\n' + formatted}
    return {'response': response}