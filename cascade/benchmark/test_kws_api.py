"""测 KWS 服务（8002）：POST 音频，看 detected/rejected。"""
import io
import sys
import urllib.request
import uuid


def detect(audio_path):
    with open(audio_path, "rb") as f:
        data = f.read()
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="file"; filename="a.wav"\r\n')
    body.write(b"Content-Type: audio/wav\r\n\r\n")
    body.write(data)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        "http://localhost:8002/detect",
        data=body.getvalue(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return resp.read().decode()


for p in sys.argv[1:]:
    print(f"{p}: {detect(p)}")
