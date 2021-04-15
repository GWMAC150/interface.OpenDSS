'''
    OpenDSS RIAPS device
    
    Model fragment:
    
    app APP {
        message CommandReq;
        message CommandRep;
        message Measurement;

    device OpenDSS {
        ans command : (CommandReq, CommandRep);
        pub data : Measurement;
        inside relay;
    }

    A compatible component must access the device component via a 
    matching qry port.  
    
    Message types and protocol
    
    All messages are Python objects, as shown below. Elements with UpperCase names are to be set by the app.  
    
    - CommandReq: The client component uses these messages to control the agent.
      [ 'sub', (ObjectName, AttributeName, Unit) ] - instruct the agent to start publishing measurement data from the Object.Attribute of the model. 
      [ 'pub', (ObjectName, AttributeName, Value, Unit)] - set the value of the selected Object.Attribute. 
      [ 'qry', (ObjectName, AttributeName, Unit) ] - query the last known value of the Object.Attribute. 
    - CommandRep: The agent replies with these messages to the commands.
      'ok' - Reply for 'sub', 'pub', commands
      (ObjectName, AttributeName, Value, Unit, TimeStamp) - Response to query, the value of the requested Object.Attribute.
    - Measurement: Data messages that are published by the agent (as requested by a 'sub' command)
      (ObjectName, AttributeName, Value, Unit, TimeStamp) - The value of the selected Object.Attribute.
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
from riaps.utils import spdlog_setup
import spdlog
from rpyc.utils.factory import DiscoveryError
from riaps.run.comp import Component

rpyc.core.protocol.DEFAULT_CONFIG['allow_pickle'] = True

DSSACLIENT_ENDPOINT = 'inproc://dssa-client'
DSSACLIENT_DATA_ENDPOINT = 'inproc://dssa-client-datal'

class DSSAClient(threading.Thread):
    SERVICENAME = 'RIAPS_DSSA'
    RECONNECT = False
    def __init__(self,owner,name,host,port,trigger,logger):
        threading.Thread.__init__(self)
        self.owner = owner
        # loggerName = self.owner.getActorName() + '.' + self.owner.getName() + '.' + 'GLAClient'
        self.logger = logger # spdlog.ConsoleLogger(loggerName,True,True,False)
        # self.logger.set_pattern(spdlog_setup.global_pattern)
        # self.logger.set_level(spdlog.LogLevel.DEBUG)
        self.name = name
        self.host = host
        self.port = port
        self.relay = None
        self.trigger = trigger
        self.bgsrv = None
        self.bgsrv_data_outer = None
        self.bgsrv_data_inner = None
        self.active = threading.Event()
        self.active.clear()
        self.terminated = threading.Event()
        self.terminated.clear()
        self.lock = RLock()
        self.poller = None
        self.subs = []
        self.queries = []
        self.conn = None
        self.context = zmq.Context()
    
    def login(self,retry = True):
        self.logger.info("login()")
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
                self.logger.info("discovery of %s failed" % (DSSAClient.SERVICENAME))
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
            self.logger.info("subscribing")
            with self.lock: 
                for sub in subs:
                    self.conn.root.subscribe(sub)
        else:
            self.subs = subs

    def publish(self,pubs):
        if self.conn:
            with self.lock:
                for pub in pubs:
                    self.conn.root.publish(pub)
        else:
            self.pubs = pubs
            
    def reply(self,id,msg):
        try: 
            cmd = msg[0]
            assert(cmd == 'ans')
            rep = [cmd,id] + [msg[1:]]
            self.logger.info("run: sending reply = %s" % str(rep))
            self.relay.send_pyobj(rep)
        except:
            info = sys.exc_info()
            self.logger.error("Error in reply '%s': %s %s" % (cmd, info[0], info[1]))
            traceback.print_exc()
            raise
    
    def query(self, id, queries):
        if self.conn:
            with self.lock: 
                for query in queries:
                    result = self.conn.root.query(query)
                    self.reply(id,result)
        else:
            self.queries = queries
            
    def setup(self):
        self.logger.info("setup()")
        self.relay = self.trigger.setupPlug(self)
        self.poller = zmq.Poller()
        self.poller.register(self.relay,zmq.POLLIN)
        self.bgsrv_data_outer = self.context.socket(zmq.PAIR)
        global DSSACLIENT_DATA_ENDPOINT
        self.bgsrv_data_outer.bind(DSSACLIENT_DATA_ENDPOINT)
        self.poller.register(self.bgsrv_data_outer,zmq.POLLIN)
        
    def run(self):
        self.setup()
        ok = True
        while True:
            self.active.wait(None)                  # Events to handle activation/termination
            if self.terminated.is_set(): break
            if self.active.is_set():
                ok = self.login(True)
                if ok: self.logger.info("run: loop...")
                while ok:
                    try:
                        sockets = dict(self.poller.poll(1000.0))
                        if self.terminated.is_set(): break
                        toDelete = []
                        for s in sockets:
                            if s == self.relay:
                                self.logger.info("checking relay")
                                msg = self.relay.recv_pyobj()
                                # msg = ['sub', ( obj, attr, unit ) ... ] -- Subscribe   
                                # msg = ['pub', ( obj, attr, unit ) ... ] -- Publish
                                # msg = ['qry', id, ( obj, attr, unit ) ... ] -- Query 
                                self.logger.info("run: relay recv = %s" % str(msg))
                                cmd = msg[0]
                                if cmd == 'sub':
                                    self.subscribe(msg[1:])
                                elif cmd == 'pub': 
                                    self.publish(msg[1:])
                                elif cmd == 'qry':
                                    self.query(msg[1],msg[2:])
                                else:
                                    self.logger.error('run: error in command: %s' % str(msg))
                            elif s == self.bgsrv_data_outer:
                                msg = self.bgsrv_data_outer.recv_pyobj()
                                self.logger.info("run: sending data = %s" % str(msg))
                                self.relay.send_pyobj(msg)
                            else:
                                pass        # Spurious socket? 
                            toDelete += [s]
                        for s in toDelete:
                            del sockets[s]
                    except:
                        traceback.print_exc()
                        ok = False
                    if self.terminated.is_set() or (self.bgsrv == None and self.conn == None): break
            if self.terminated.is_set(): break
            if DSSAClient.RECONNECT:
                self.logger.info("Connection to controller lost - retrying")
                continue
            else:
                break
        self.logger.info('DSSAClient terminated')
    
    def setupBgSocket(self):
        global DSSACLIENT_DATA_ENDPOINT
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
            if cmd == 'sendClient':
                self.bgsrv_data_inner.send_pyobj(msg)
            else:
                pass
        except:
            info = sys.exc_info()
            self.logger.error("Error in callback '%s': %s %s" % (cmd, info[0], info[1]))
            traceback.print_exc()
            raise
        return reply

    def activate(self):
        self.active.set()
        self.logger.info('DSSAClient activated')
                    
    def deactivate(self):
        self.active.clear()
        self.logger.info('DSSAClient deactivated')
    
    def terminate(self):
        self.active.set()
        self.terminated.set()
        self.logger.info('DSSAClient terminating')
    
    def get_plug(self):
        return self.relay

class OpenDSS(Component):
    def __init__(self, host='', port=0):
        super(OpenDSS, self).__init__()
        self.logger.info("OpenDSS.__init__()")
        self.host = host
        self.port = port
        self.running = False
        self.DSSAClient = None
        
    def handleActivate(self):
        self.logger.info("OpenDSS.handleActivate()")
        try:
            clientName = "DSSA-%s" % str(hex(int.from_bytes(self.getActorID(),'big')))
            self.DSSAClient = DSSAClient(self,clientName,self.host,self.port,self.relay,self.logger)
            self.DSSAClient.start()         # Run the thread
            plug = None
            while plug is None:
                plug = self.glaClient.get_plug()
            time.sleep(0.1)
            self.plugID = self.relay.get_plug_identity(plug)
            self.relay.activate()
            self.DSSAClient.activate()
            self.running = True
        except Exception as e:
            self.logger.error('Exception: %s' % str(e))
            if self.DSSAClient != None:
                self.DSSAClient.stop()
            
    def on_command(self):
        msg = self.command.recv_pyobj()
        self.logger.info("on_command(): %s" % str(msg))
        cmd = msg[0]
        if not self.running:
            self.logger.info("DSSA Client not running")
            return
        if cmd == 'pub' : 
            # msg = [ 'pub'  , ( 'obj', 'attr', 'unit' ) ... ] -- Publish
            self.relay.set_identity(self.plugID)
            self.relay.send_pyobj(msg)
            self.command.send_pyobj('ok')
        elif cmd == 'sub':
            # msg = [ 'sub'  , ( 'obj', 'attr', 'unit' ) ... ] -- Subscribe
            self.relay.set_identity(self.plugID)   
            self.relay.send_pyobj(msg)
            self.command.send_pyobj('ok')
        elif cmd == 'qry':
            # msg = [ 'qry'  , ( 'obj', 'attr', 'unit' ) ... ] -- Query
            id = self.command.get_identity()
            qry = [cmd,id] + msg[1:]
            self.relay.set_identity(self.plugID)
            self.relay.send_pyobj(qry)
        else:
            self.logger.error("OpenDSS.on_command: unknown command: %s" % str(msg))
    
    def on_relay(self):
        msg = self.relay.recv_pyobj()
        self.logger.info("on_relay(): recv = %s" % str(msg))
        cmd = msg[0]
        if cmd == 'sendClient':
            data = msg[1:]
            self.data.send_pyobj(data)
        elif cmd == 'ans': 
            id,ans = msg[1],msg[2]
            self.command.set_identity(id)
            self.command.send_pyobj(ans)
        else:
            pass

    def __destroy__(self):
        self.logger.info("__destroy__")
        self.running = False
        self.DSSAClient.deactivate()
        self.DSSAClient.terminate()
        self.DSSAClient.join()
        self.logger.info("__destroy__ed")
        
        
