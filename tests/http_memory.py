"""Exercise the real HTTP parser/Handler without opening any network sockets."""
import http.client
from http.cookies import SimpleCookie
import io
import json
import threading
from types import SimpleNamespace
from server import Handler, initialize, connect, MODULES
from telegram_service import Config

SERVERS = {}


class MemoryServer(SimpleNamespace):
    def serve_forever(self):
        self.stop.wait()

    def shutdown(self):
        self.stop.set()

    def server_close(self):
        self.stop.set()


def create_memory_server(host='127.0.0.1', port=0, db_path=None):
    initialize(db_path)
    with connect(db_path) as db:
        for module in MODULES:
            if hasattr(module,'startup'):
                module.startup(db)
    port = 9000+len(SERVERS)
    server = MemoryServer(db_path=str(db_path),telegram_config=Config(),server_port=port,server_name='localhost',stop=threading.Event())
    SERVERS[f'http://127.0.0.1:{port}'] = server
    return server


class Socket:
    def __init__(self, raw):
        self.input, self.output = io.BytesIO(raw), bytearray()

    def makefile(self, *args, **kwargs):
        return self.input

    def sendall(self, value):
        self.output.extend(value)


class MemoryClient:
    def __init__(self, base):
        self.base, self.csrf, self.cookie = base, '', ''

    def request(self, path, method='GET', data=None, headers=None):
        payload = json.dumps(data).encode() if data is not None else b''
        values = {'Host':self.base.split('//')[1], 'Content-Type':'application/json', 'X-CSRF-Token':self.csrf, 'Cookie':self.cookie, **(headers or {})}
        values['Content-Length'] = str(len(payload))
        raw = f'{method} {path} HTTP/1.0\r\n'+''.join(f'{key}: {value}\r\n' for key,value in values.items())+'\r\n'
        socket = Socket(raw.encode()+payload)
        Handler(socket,('127.0.0.1',1234),SERVERS[self.base])
        response = http.client.HTTPResponse(Socket(bytes(socket.output)))
        response.begin()
        body = response.read()
        if response.headers.get('Set-Cookie'):
            cookie = SimpleCookie(response.headers['Set-Cookie'])
            self.cookie = '; '.join(f'{key}={value.value}' for key,value in cookie.items() if value.value)
        if 'application/json' in response.headers.get('Content-Type',''):
            body = json.loads(body)
        return response.status,body,response.headers

    def login(self, email, password='demo2026'):
        if '@' not in email:
            email += '@atu.kz'
        status,body,_ = self.request('/api/login','POST',{'email':email,'password':password})
        assert status == 200, body
        status,data,_ = self.request('/api/me')
        assert status == 200, data
        self.csrf,self.user = data['csrf'],data['user']
        return self

    def get(self,path):
        return self.request(path)

    def post(self,path,data=None):
        return self.request(path,'POST',data if data is not None else {})

    def put(self,path,data):
        return self.request(path,'PUT',data)
