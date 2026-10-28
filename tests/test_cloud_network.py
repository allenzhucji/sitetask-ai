import threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from PySide6.QtCore import QObject,QThread,Signal,Slot,Qt
from app.services.cloud_network import CloudNetworkWorker

class Controller(QObject):
    send=Signal(int,str,object)
    stop=Signal()
    def __init__(self):super().__init__();self.results=[]
    @Slot(int,int,str,object)
    def received(self,*args):self.results.append(args)

@pytest.mark.parametrize('mode',['redirect','oversize','slow','stop'])
def test_transport_limits_and_abort(qtbot,mode):
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            requests.append(self.path);self.rfile.read(int(self.headers.get('Content-Length','0')))
            try:
                if mode in ('slow','stop'):
                    self.send_response(200);self.end_headers();self.wfile.write(b'{');self.wfile.flush();time.sleep(1)
                elif mode=='redirect':
                    self.send_response(302);self.send_header('Location','http://127.0.0.1:'+str(self.server.server_port)+'/leaked');self.end_headers()
                else:
                    self.send_response(200);self.end_headers();self.wfile.write(b'x'*(300*1024))
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    driver=Controller();thread=QThread();worker=CloudNetworkWorker('http://127.0.0.1:'+str(server.server_port),'stb_test',True,timeout_ms=150 if mode=='slow' else 20000)
    worker.moveToThread(thread);driver.send.connect(worker.request,Qt.ConnectionType.QueuedConnection);driver.stop.connect(worker.stop,Qt.ConnectionType.QueuedConnection)
    worker.response.connect(driver.received,Qt.ConnectionType.QueuedConnection);worker.stopped.connect(thread.quit,Qt.ConnectionType.DirectConnection);thread.finished.connect(worker.deleteLater)
    thread.start()
    try:
        driver.send.emit(1,'/v1/bridge/pull',{})
        qtbot.waitUntil(lambda:bool(requests),timeout=3000)
        if mode=='stop':driver.stop.emit()
        qtbot.waitUntil(lambda:bool(driver.results),timeout=3000)
        assert requests==['/v1/bridge/pull']
        if mode=='redirect':assert driver.results[0][2]=='redirect_refused'
        if mode=='oversize':assert driver.results[0][2]=='response_too_large'
        if mode=='slow':assert driver.results[0][2] in ('total_timeout','network_error')
    finally:
        driver.stop.emit();qtbot.waitUntil(lambda:not thread.isRunning(),timeout=3000);server.shutdown();server.server_close()
