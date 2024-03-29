'''
    OpenDSS Agent Test Client
'''

import time
import sys
import os,signal
import logging
import socket
import traceback
import argparse
import threading
from threading import RLock
import zmq
import rpyc
import rpyc.core
import rpyc.utils
from rpyc.utils.factory import DiscoveryError

rpyc.core.protocol.DEFAULT_CONFIG['allow_pickle'] = True

DSSACLIENT_ENDPOINT = 'inproc://dssa-client'
DSSACLIENT_DATA_ENDPOINT = 'inproc://dssa-client-data'

class DSSAClient(threading.Thread):
    SERVICENAME = 'RIAPS_DSSA'
    RECONNECT = False
    def __init__(self,name,host,port,context):
        threading.Thread.__init__(self)
        self.logger = logging.getLogger(__name__)
        self.name = name
        self.host = host
        self.port = port
        self.context = context
        self.bgsrv = None
        self.bgsrv_data_outer = None
        self.bgsrv_data_inner = None
        self.lock = RLock()
        self.poller = None
        self.subs = []
        self.conn = None
    
    def login(self,retry = True):
        self.conn = None
        while True:
            try:
                addrs = rpyc.utils.factory.discover(DSSAClient.SERVICENAME)
                for host,port in addrs:
                    try:
                        self.conn = rpyc.connect(host,port,
                                                 config = {"allow_public_attrs" : True})
                    except socket.error as e:
                        print("%s.%s: %s" %(str(host),str(port),str(e)))
                        pass
                    if self.conn: break
            except DiscoveryError:
                pass
            if self.conn: break
            if self.host and self.port:
                try:
                    self.conn = rpyc.connect(self.host,self.port,
                                             config = {"allow_public_attrs" : True})
                except socket.error as e:
                    print("%s.%s: %s" %(str(host),str(port),str(e)))
                    pass
            if self.conn: break
            if retry == False:
                return False
            else:
                time.sleep(5)
                continue
        self.bgsrv = rpyc.BgServingThread(self.conn,self.handleBgServingThreadException)
        resp = None
        try:       
            resp = self.conn.root.login(self.name,self.callback)
        except:
            traceback.print_exc()
            pass
        return type(resp) == tuple and resp[0] == 'ok'


    def subscribe(self,subs):
        if self.conn:
            with self.lock: 
                for sub in subs:
                    self.conn.root.subscribe(sub)
        else:
            self.subs = subs

    def publish(self,pub):
        with self.lock:
            self.conn.root.publish(pub)
            
    def query(self, queries):
        if self.conn:
            with self.lock: 
                for query in queries:
                    result = self.conn.root.query(query)
                    return(result)
        else:
            self.queries = queries

    def setup(self):
        self.poller = zmq.Poller()
        self.control = self.context.socket(zmq.PAIR)
        global DSSACLIENT_ENDPOINT
        self.control.connect(DSSACLIENT_ENDPOINT)
        self.poller.register(self.control,zmq.POLLIN)
        self.bgsrv_data_outer = self.context.socket(zmq.PAIR)
        global DSSACLIENT_DATA_ENDPOINT
        self.bgsrv_data_outer.bind(DSSACLIENT_DATA_ENDPOINT)
        self.poller.register(self.bgsrv_data_outer,zmq.POLLIN)
        
    def run(self):
        self.setup()
        self.killed = False
        while True:
            if self.killed: break
            ok = self.login(True)
            if ok and len(self.subs) > 0:
                self.subscribe(self.subs)
            while ok:
                try:
                    sockets = dict(self.poller.poll())
                    for s in sockets:
                        if s == self.control:
                            msg = self.control.recv_pyobj()
                            self.publish(msg)
                        elif s == self.bgsrv_data_outer:
                            msg = self.bgsrv_data_outer.recv_pyobj()
                            self.control.send_pyobj(msg)
                        else:
                            pass
                except:
                    traceback.print_exc()
                    ok = False
                if self.killed or (self.bgsrv == None and self.conn == None): break
            if self.killed: break
            if DSSAClient.RECONNECT:
                self.logger.info("Connection to controller lost - retrying")
                continue
            else:
                break
        pass
    
    def setupBgSocket(self):
        global DSSALIENT_DATA_ENDPOINT
        self.bgsrv_data_inner = self.context.socket(zmq.PAIR)
        self.bgsrv_data_inner.connect(DSSACLIENT_DATA_ENDPOINT)
        
    def handleBgServingThreadException(self):
        self.bgsrv = None
        self.conn = None
        self.bgsrv_data_inner.close()
        self.bgsrv_data_inner = None
        
    def callback(self,msg):
        '''
        Callback from server - runs in the the background server thread  
        '''
        assert type(msg) == tuple
        if self.bgsrv_data_inner == None: self.setupBgSocket()
        
        reply = None
        try: 
            cmd = msg[0]
            print ('callback %s', str(msg))
            self.bgsrv_data_inner.send_pyobj(msg)
        except:
            info = sys.exc_info()
            self.logger.error("Error in callback '%s': %s %s" % (cmd, info[0], info[1]))
            traceback.print_exc()
            raise
        return reply

    def stop(self):
        self.logger.info("stopping")
        self.killed = True
        self.logger.info("stopped")



running = False

def terminate():
    global running
    running = False
   
def control():  
        val = '1' if control.counter < control.duty else '0'
        control.counter = (control.counter + 1) % control.period
        return val
control.counter = 0
control.period = 20
control.duty = 10 
    
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-p","--port", type=int,default=0,help="server port number")
    parser.add_argument("-n","--host", type=str,default='',help="server host address")
    args = parser.parse_args()
#
    signal.signal(signal.SIGTERM,terminate)
    signal.signal(signal.SIGINT,terminate)
    context = zmq.Context()
    
    command = context.socket(zmq.PAIR)  # Command to GLAClient thread 
    command.bind(DSSACLIENT_ENDPOINT)
    poller = zmq.Poller()
    poller.register(command, zmq.POLLIN)
                    
    try:
        clientName = "client-%s" % str(os.getpid())
        theDRunner = DSSAClient(clientName,args.host,args.port, context)
        theDRunner.subscribe([("Line", "L11", "Voltages")]) # Subscribe interface
        theDRunner.start()         # Run the thread

        running = True
        msg = None

        while running:
            sockets = dict(poller.poll(1000.0))
            if not running: break 
            for s in sockets:
                if s == command:
                    msg = command.recv_pyobj()
                    print(msg)
                else:
                    pass
            if msg:
                result = theDRunner.query([("Load","S11a","kvar")]) # Query interface
                print(result)
                kvar = float(result[4])
                duty = control()
                if duty == '1':
                    cmd = ("Load","S11a","kvar",kvar/2) # publish interface
                elif duty == '0':
                    cmd = ("Load","S11a","kvar",kvar*2) # publish interface
                print(cmd)
                command.send_pyobj(cmd)
            msg = None
            if not running: break
    
        theDRunner.join()
    except Exception as e:
        logging.error('Exception: %s' % str(e))
        if theDRunner != None:
            theDRunner.stop()
    #print ("Unexpected error:", sys.exc_info()[0])
    os._exit(0)
    
    pass
    
