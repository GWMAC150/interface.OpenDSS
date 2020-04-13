'''
Created on Feb 2, 2020

@author: ghoshp
'''

import sys
import os.path
import subprocess
import traceback
import time
import datetime
import signal
import yaml
import re
from collections import namedtuple
from threading import RLock
import json
import win32com.client
import pythoncom
from threading import Event
 
from dssa.server import ServiceThread
from dssa.config import Config
from dssa.dbase import Database
        
# namedtuple 
Subscribe = namedtuple("Subscriber", "client obj name attr")
Publish   = namedtuple("Publish", "client obj name attr value")
LogSpec   = namedtuple("LogSpec", "obj name attr")

class Agent():
    TIME_FORMAT = "%Y-%m-%d %Y %H:%M:%S"
    def __init__(self,baseName,path):
        self.base = baseName
        self.model = baseName + '.dss'
        self.logs  = baseName + '.dsl'
        self.cfile = 'dssa.yaml'
        self.modelpath = path
        self.StopFlag = False
        self.ContinueFlag = Event()
        self.ContinueFlag.set()
        assert os.path.isfile(self.model)
        assert os.path.isfile(self.logs)
        assert os.path.isfile(self.cfile)
        
        try:
            Config.setup()
            with open(self.cfile,'r') as f:
                    self.conf = yaml.load(f,Loader=yaml.Loader)
        except:
                raise
                
        self.conf.time_delta = Config.convert_duration(self.conf.time_delta)
        self.conf.wait_for_cmd = Config.convert_duration(self.conf.wait_for_cmd)     
        assert Config.convert_duration(self.conf.stepsize) > self.conf.wait_for_cmd, "Simulation step size must be greater than the waiting period for the controller response"
        assert self.conf.time_delta > self.conf.wait_for_cmd, "The physical time step must be greater than the waiting period for the controller response"
            
        if self.conf.time_base == "now":
            self.time = datetime.datetime.utcnow()
        else:
            self.time =  datetime.datetime.strptime(self.conf.time_base,"%Y-%m-%d")
            
        self.logSpec = {}
        try:
            with open(self.logs,'r') as f:
                content = json.load(f)
                for item in content:
                    (obj,name,attr) = item
                    key = '%s.%s.%s' % (obj,name,attr)
#                    drop =  re.compile(r' %s'% unit)
                    self.logSpec[key] = LogSpec(obj=obj,attr=attr,name=name)
        except:
            raise
        
        self.subs = {}  # obj.attr -> Subscribe
        self.pubs = []  # [Publish]*
        self.clients = {} 
        self.clientSubs = {}
        self.results = {} 
        self.lock = RLock()

    def launch(self,cmd,logfile,env):
        context = os.environ.copy()
        context.update(env)
        with open(logfile,"ab") if logfile else None as log:
            try:
                process = subprocess.Popen(cmd,env=context,stdout=log,stderr=subprocess.STDOUT)
            except:
                traceback.print_exc()
                print('launch error: %s' % sys.exc_info()[0])
                process = None
        return process
    
    def start(self):
        self.service = ServiceThread(self,self.conf.host,self.conf.port,self.conf.registry_ip)
        self.service.start() 
        self.dbase = Database(self.conf,self.logSpec)
        pythoncom.CoInitialize()
        self.engine = win32com.client.Dispatch("OpenDSSEngine.DSS")
        self.engine.Start("0")


# use the Text interface to OpenDSS
        self.text = self.engine.Text
        self.text.Command = "clear"
        self.circuit = self.engine.ActiveCircuit
        self.Solution = self.circuit.Solution
        self.element = self.circuit.ActiveCktElement
        self.lock = RLock()

        print(self.engine.Version)
        
    def run(self):
        
        time_advance = datetime.timedelta(seconds=Config.convert_duration(self.conf.stepsize))

# Select the model and set the required parameters
        mode = self.conf.mode
        stepsize = self.conf.stepsize
        number = self.conf.number_of_steps
        wait_for_cmd = self.conf.wait_for_cmd
        self.text.Command = "compile [" + self.modelpath + '\\' + self.model + "]"
        self.text.Command = "New EnergyMeter.Feeder Line.L115 1"
# Set the simulation mode, step size and the duration
        self.text.Command = "set mode=%s stepsize=%s number=%d" % (mode,stepsize, number)
        originalSteps = self.Solution.Number
        self.Solution.Number = 1    # this steps the simulation by one at a time
        self.Solution.MaxControlIterations = 20 # prevent the control loop from cycling infinitely
        actionMap = {0: self.set_received_commands} # hash map for the control action
        hour = 0
        for steps in range(originalSteps):
            if self.StopFlag:
                break
            self.ContinueFlag.wait()
            pubList = []
            time1 = time.perf_counter()
            self.text.Command = "get time"
            now = self.text.Result
            print("Timestamp: %s" % (str(now)))
            with self.lock:
                for key in self.subs:
                    for sub in self.subs[key]:
                        self.circuit.SetActiveElement(sub.obj+'.'+sub.name)
                        res = getattr(self.element,sub.attr)
                        print("sub: %s.%s.%s = %s" % (sub.obj,sub.name,sub.attr, str(res)))
                        sub.client.sendClient(sub.obj,sub.name,sub.attr,res,now)
                        self.results[key] = (sub.obj,sub.name,sub.attr,res,now)
                    if key in self.logSpec:
                        # send result
                        self.dbase.log(self.time,self.logSpec[key],res)
            self.Solution.InitSnap()    # perform initial solve
            iteration = 0
            while not self.Solution.ControlActionsDone:
                self.Solution.SolveNoControl()  # power flow calculations without control
                devicehandle = actioncode = 0
                if iteration == 0:
                    countdown = wait_for_cmd
                    sec = 0
                    while countdown > 0:
                        time.sleep(1)    # wait for control commands
                        sec = sec + 1
                        with self.lock:
                            pubList.append(self.pubs)
                            self.pubs = []
                        # push the control action into queue
                        if len(pubList[actioncode]) > 0:
                            self.circuit.CtrlQueue.Push(hour, sec, actioncode, devicehandle)
                        actioncode += 1
                        countdown = countdown - 1
                self.Solution.CheckControls()   # OpenDSS pushes active to queue
                # get items from the control action list
                # that needs to be handled now
                while self.circuit.CtrlQueue.PopAction != 0:
                    devicehandle = self.circuit.CtrlQueue.DeviceHandle
                    actioncode = self.circuit.CtrlQueue.ActionCode
                    actionFunction = actionMap[devicehandle]
                    actionFunction(pubList[actioncode])
                iteration += 1
                if iteration >= self.Solution.MaxControlIterations:
                    print("Maximum Control Iterations reached!!!")
                    break
            
            self.Solution.FinishTimeStep()
            
            self.dbase.flush()
# keep track of time steps in simulation time for logging
            self.time = self.time + time_advance
# step the simulation
            time2 = time.perf_counter()
            timeelapsed = time2 - time1
            duration = self.conf.time_delta - timeelapsed
            if duration > 0:
                time.sleep(duration)
        self.stop()
            
    def set_received_commands(self,pubs):
        with self.lock:
            self.text.Command = "get time"
            now = self.text.Result
            for pub in pubs:
                print(now, pub.obj, pub.name, pub.attr, pub.value)
                if pub.value == 'Open' or pub.value == 'Close':
                    self.text.Command = "%s %s.%s 1" %(pub.value, pub.obj, pub.name)
                else:
                    self.circuit.SetActiveElement(pub.obj+'.'+pub.name)
#                    curr_val = self.element.Properties(pub.attr).Val
                    self.element.Properties(pub.attr).Val = pub.value
                key = "%s.%s.%s" %(pub.obj, pub.name, pub.attr)
                self.results[key] = (pub.obj,pub.name,pub.attr,pub.value,now)
                if key in self.logSpec:
                    self.dbase.log(self.time,self.logSpec[key],pub.value)

    def terminate(self,_ign1,_ign2):
        self.stop()
                        
    def stop(self):
        with self.lock:
            self.StopFlag = True
        try: self.service.stop()
        except: pass
#        try: self.broker.kill()
#        except: pass
#        try: self.engine.kill()
#        except: pass
        try: self.dbase.stop()
        except: pass
               
    def subscribe(self,client,sub):
        obj,name,attr = sub
        key = '%s.%s.%s' % (obj,name,attr)
#        drop =  re.compile(r' %s'% unit)
        with self.lock:
            if key not in self.subs: self.subs[key] = []
            self.subs[key] += [Subscribe(client=client,obj=obj,name=name,attr=attr)]
            clientHash = hash(client)
            if clientHash not in self.clientSubs:
                self.clientSubs[clientHash] = set()
            self.clientSubs[clientHash].add(key)
            
    def query(self,client,query):
        obj,name,attr = query
        key = '%s.%s.%s' % (obj,name,attr)
        with self.lock:
            if key in self.results:
                res = self.results[key]
                return ('ans',res[0],res[1],res[2],res[3],res[4])
            else:
                self.circuit.SetActiveElement(obj+'.'+name)
                val = str(self.element.Properties(attr).Val)
                self.text.Command = "get time"
                now = self.text.Result
                if val:
                    self.results[key] = (obj,name,attr,val,now)
                    return ('ans', obj,name,attr,val,now)
                else:
                    return('ans',)
        
    def publish(self,client,pub):
        obj,name,attr,value = pub
        with self.lock:
            self.pubs += [Publish(client=client,obj=obj,name=name,attr=attr,value=value)]
        
    def unsubscribe(self,client,sub=None):
        if sub != None:
            obj,name,attr = sub
            key = '%s.%s.%s' % (obj,name,attr)
            with self.lock:
                assert key in self.subs
                self.subs[key] = filter(lambda sub: sub.client == client, self.subs[key])
        else:
            clientHash = hash(client)
            with self.lock:
                if clientHash in self.clientSubs:
                    for subKey in self.clientSubs[clientHash]:
                        self.subs[subKey] = list(filter(lambda sub: sub.client != client, self.subs[subKey]))
                    del self.clientSubs[clientHash]
                
    def isClient(self,name):
        return name in self.clients
    
    def addClient(self,name,client):
        with self.lock:
            self.clients[name] = client
    
    def delClient(self,name):
        with self.lock:
            del self.clients[name]
            
    def handle_pause(self,pause_flag):
        if pause_flag:
            self.ContinueFlag.clear()
        else:
            self.ContinueFlag.set()
