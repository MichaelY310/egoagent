import socket
import sys

print("=== Test 1: TCP Connectivity ===", flush=True)
s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(('fdbd:dc05:5:132::25', 11235))
    print('TCP CONNECTED', flush=True)
    s.close()

    print("\n=== Test 2: Chat API ===", flush=True)
    import requests
    r = requests.post('http://[fdbd:dc05:5:132::25]:11235/v1/chat/completions', json={
        'model': '/qs_service/model_compiled/DeepSeek-R1-Distill-Qwen-1.5B-demo1',
        'messages': [{'role': 'user', 'content': 'say hi'}],
        'max_tokens': 10
    }, timeout=30)
    content = r.json()['choices'][0]['message']['content']
    print(f'API Response: {content}', flush=True)
    print('SUCCESS', flush=True)
except Exception as e:
    print(f'FAIL: {e}', flush=True)
    sys.exit(1)
