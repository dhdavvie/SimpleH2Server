import sys
import logging
import time
from uuid import uuid4

from OpenSSL import crypto
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.internet.protocol import Protocol, Factory
from twisted.internet import endpoints, reactor, ssl

import h2
from h2.utilities import extract_method_header
from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import (
    RequestReceived, DataReceived, WindowUpdated
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)


class Request:

    def __init__(self, event):
        self.stream_id = event.stream_id
        self.headers = dict((key.decode('utf-8'), val.decode('utf-8')) for key, val in event.headers)


class H2Protocol(Protocol):
    def __init__(self):
        config = H2Configuration(client_side=False)
        self.conn = H2Connection(config=config)
        self.uuid = uuid4()

    def connectionMade(self):
        logger.debug("(%s) Connection made" % self.uuid)
        self.conn.initiate_connection()
        self.transport.write(self.conn.data_to_send())

    # This is called when data is being received from the client
    def dataReceived(self, data):

        events = self.conn.receive_data(data)

        if self.conn.data_to_send:
            self.transport.write(self.conn.data_to_send())

        for event in events:
            if isinstance(event, RequestReceived):
                req = Request(event)
                self.request_received(req)

    # This parses the received request
    def request_received(self, req):
        assert req.headers[':method'] == 'GET'

        stream_id = req.stream_id
        
        if req.headers[':path'] == '/':
            response_data = b'<html>Hello world!</html>'
            status = '200'
            logger.debug("(%s) GET request" % self.uuid)
        else:
            status = '404'
            response_data = b'Not Found'

        self.conn.send_headers(
            stream_id=stream_id,
            headers=[
                (':status', status),
                ('server', 'basic-h2-server/1.0'),
                ('content-length', str(len(response_data))),
                ('content-type', 'text/html'),
            ],
        )

        self.conn.send_data(
            stream_id=stream_id,
            data=response_data,
            end_stream=True
        )
        to_send = self.conn.data_to_send()
        
        self.transport.write(to_send)

        # logger.debug("(%s) SENDING: " % self.uuid + to_send)

        return


class H2Factory(Factory):
    def buildProtocol(self, addr):
        return H2Protocol()

with open('server.crt', 'r') as f:
    cert_data = f.read()
with open('server.key', 'r') as f:
    key_data = f.read()

# Setup SSL stuff
cert = crypto.load_certificate(crypto.FILETYPE_PEM, cert_data)
key = crypto.load_privatekey(crypto.FILETYPE_PEM, key_data, 'test')
options = ssl.CertificateOptions(
    privateKey=key,
    certificate=cert,
    acceptableProtocols=[b'h2'],
)

# Launch server
endpoint = endpoints.SSL4ServerEndpoint(reactor, 8080, options, backlog=128)
endpoint.listen(H2Factory())
reactor.run()