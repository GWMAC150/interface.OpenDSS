
import rpyc
import socket
from rpyc.utils.factory import DiscoveryError
import threading
from threading import RLock

NAME = "RIAPS_DSSA"

class OpenDSSClient(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.conn = None
        self.subs = []
        self.pubs = []
        self.lock = RLock()
        
    def subscribe(self,subs):
        if self.conn:
            with self.lock: 
                for sub in subs:
                    self.conn.root.subscribe(sub, self.callback)
        else:
            self.subs = subs
            
    def publish(self,pubs):
        if self.conn:
            with self.lock:
                for pub in pubs:
                    self.conn.root.publish(pub)
        else:
            self.pubs = pubs
    
    def callback(self,msg):
        print ('callback %s', str(msg))
    
    def connect(self):
        try:
            addrs = rpyc.discover(NAME)
            for host,port in addrs:
                try:
                    self.conn = rpyc.connect(host,port,
                                             config = {"allow_public_attrs" : True})
                except socket.error as e:
                    print("%s.%s: %s" %(str(host),str(port),str(e)))
                    pass
                if self.conn: break
        except DiscoveryError:
            print("discovery of %s failed" % (NAME))
            pass
    def run(self):
        self.connect()
        self.subscribe([("Line", "L11", "Voltages")])
    
if __name__ == '__main__':
    
    try:
        
        OpenDSSAgent = OpenDSSClient()
#         OpenDSSAgent.subscribe([("Line", "L11", "Powers")]) # Subscribe
        OpenDSSAgent.start()         # Run the thread

        running = True

        '''while running:
            sockets = dict(poller.poll(1000.0))
            if not running: break 
            for s in sockets:
                if s == command:
                    msg = command.recv_pyobj()
                    print(msg)
                else:
                    pass
            cmd = control()
            print(cmd)
            command.send_pyobj(cmd)
            if not running: break
    
        theGRunner.join()
    except Exception as e:
        logging.error('Exception: %s' % str(e))
        if theGRunner != None:
            theGRunner.stop()
    #print ("Unexpected error:", sys.exc_info()[0])
    os._exit(0)'''
        while running:
            if not running: break
        OpenDSSClient.join()
    except:
        print("could not start Client")
    
    pass