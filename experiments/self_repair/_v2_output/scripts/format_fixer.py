def run(ctx):
    response = ctx['response']
    # Check if final answer tag exists
    if '<final_answer>' in response:
        return {'response': response}
    # Extract last numeric value as answer
    import re
    numbers = re.findall(r'\d+\.?\d*', response)
    if numbers:
        answer = numbers[-1]
        return {'response': f'<final_answer>{answer}</final_answer>'}
    return {'response': response}