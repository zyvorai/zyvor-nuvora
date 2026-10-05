import time
import urllib.request
for _ in range(100):
    try:
        urllib.request.urlopen('http://127.0.0.1:8789/healthz',timeout=1)
        break
    except OSError:
        time.sleep(.1)
else:
    raise SystemExit('Server did not become ready')
