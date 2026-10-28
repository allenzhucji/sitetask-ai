"""Cancellable HTTP transport. All Qt network objects live on the worker thread."""
from urllib.parse import urlsplit
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply, QSslSocket
from app.services.cloud_protocol import decode
from scripts.task_queue import encode
_tls_configured = False

def configure_tls_backend():
    global _tls_configured
    import sys
    # CPython and Qt can load incompatible OpenSSL DLLs in the same Windows
    # process. Use native Windows certificate validation instead of DLL search.
    if sys.platform=='win32' and not _tls_configured:
        # Do not query activeBackend first: that initializes the default OpenSSL
        # plugin before we have selected the native backend.
        _tls_configured = QSslSocket.setActiveBackend('schannel')
        return _tls_configured
    return True

def validate_origin(url, *, local_test=False):
    p=urlsplit(url)
    local=local_test and p.scheme=='http' and p.hostname=='127.0.0.1'
    if (p.scheme!='https' and not local) or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/'):
        raise ValueError('invalid_worker_origin')
    return url.rstrip('/')

class CloudNetworkWorker(QObject):
    response=Signal(int,int,str,object)
    stopped=Signal()
    def __init__(self,origin,token,local_test=False,*,timeout_ms=20000):
        super().__init__();self.origin=validate_origin(origin,local_test=local_test);self.token=token
        self.manager=None;self.reply=None;self.stopping=False
        self.timeout_ms=max(1,min(20000,timeout_ms))

    @Slot(int,str,object)
    def request(self,serial,path,payload):
        if self.stopping or self.reply is not None:return
        if not path.startswith('/v1/bridge/') or '?' in path or '..' in path:
            self.response.emit(serial,0,'invalid_path',{});return
        if self.manager is None:
            if not configure_tls_backend():
                self.response.emit(serial,0,'tls_backend_unavailable',{});return
            self.manager=QNetworkAccessManager(self)
        request=QNetworkRequest(QUrl(self.origin+path))
        request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        request.setRawHeader(b'User-Agent',b'SiteTaskAI/1.3')
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json')
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(self.timeout_ms)
        raw=encode(payload)
        if len(raw)>256*1024:self.response.emit(serial,0,'request_too_large',{});return
        reply=self.manager.post(request,raw);self.reply=reply;buffer=bytearray();error=['']
        deadline=QTimer(reply);deadline.setSingleShot(True);deadline.setInterval(self.timeout_ms)
        def abort(code):error[0]=code;reply.abort()
        deadline.timeout.connect(lambda:abort('total_timeout'));deadline.start()
        def read():
            buffer.extend(bytes(reply.readAll()))
            if len(buffer)>256*1024:abort('response_too_large')
        reply.readyRead.connect(read)
        def finished():
            deadline.stop();read();status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
            value={};code=error[0]
            if not code:
                if 300<=status<400:code='redirect_refused'
                elif reply.error()!=QNetworkReply.NetworkError.NoError and not status:code='network_error'
                else:
                    try:value=decode(bytes(buffer),256*1024)
                    except (ValueError,UnicodeError,RecursionError):code='invalid_response'
            self.reply=None;reply.deleteLater()
            self.response.emit(serial,status,code,value)
            if self.stopping:self.stopped.emit()
        reply.finished.connect(finished)

    @Slot()
    def stop(self):
        self.stopping=True;self.token=''
        if self.reply is not None:self.reply.abort()
        else:self.stopped.emit()
