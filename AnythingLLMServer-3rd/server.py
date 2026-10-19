# -*- coding: utf-8 -*-
"""AnythingLLM 上传嵌入网页的本地服务器。
- 托管静态 index.html
- 把 /api/* 请求代理到本机 AnythingLLM Server (http://localhost:3001)
  并附加 API Key，从而让浏览器同源访问、规避 CORS。
启动: python server.py   然后浏览器打开 http://localhost:8080
"""
import http.server
import urllib.request
import urllib.error
import os

HOST = "localhost"
PORT = 8090
UPSTREAM = "http://localhost:3001"
API_KEY = "YOUR_ANYTHINGLLM_API_KEY"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.BaseHTTPRequestHandler):
    def _proxy(self, method):
        """把请求转发到上游 AnythingLLM Server。"""
        path = self.path
        # 构建上游 URL
        url = UPSTREAM + path
        body = None
        headers = {
            "Authorization": "Bearer " + API_KEY,
            "Content-Type": self.headers.get("Content-Type", "application/json"),
        }
        if method == "POST":
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                body = self.rfile.read(length)
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = resp.read()
                self.send_response(resp.status)
                # 透传一些关键响应头
                for k in ("Content-Type",):
                    if resp.headers.get(k):
                        self.send_header(k, resp.headers.get(k))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # 上游不可达等
            msg = '{"error":"proxy error: %s"}' % str(e)
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(msg.encode("utf-8"))

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_index()
        elif self.path.startswith("/api/"):
            self._proxy("GET")
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy("POST")
        else:
            self.send_error(404)

    def _serve_index(self):
        index_path = os.path.join(BASE_DIR, "index.html")
        with open(index_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        # 精简日志，避免刷屏
        print("[%s] %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    server = http.server.HTTPServer((HOST, PORT), Handler)
    print("网页地址: http://%s:%d  (代理到 %s)" % (HOST, PORT, UPSTREAM))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
