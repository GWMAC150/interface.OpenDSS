'''
Created on Feb 13, 2020

@author: ghoshp
'''

import yaml
import re

class Config(yaml.YAMLObject):
    '''
    dssa configuration object
    '''
    yaml_loader = yaml.SafeLoader
    yaml_tag = u'!DSSAConfig'
    def __init__(self,
                 host='',port=0,
                 time_base = '2000-01-01',
                 dbhost='localhost', dbport=8086, dbuser='riapsdev', dbpassword='riaps', dbname='opendss', dbdrop=True, stepsize = '15m',
                 mode = 'daily', number_of_steps = 96, time_delta = '1s', wait_for_cmd = '1s'):
        self.host = host
        self.port = port
#        self.time_stop = time_stop
#        self.time_pace = time_pace
        self.time_base = time_base
        self.dbhost = dbhost
        self.dbport = dbport
        self.dbuser = dbuser
        self.dbpassword = dbpassword
        self.dbname = dbname
        self.dbdrop = dbdrop
        self.stepsize = stepsize
        self.mode = mode
        self.number_of_steps = number_of_steps
        self.time_delta = self.convert_duration(time_delta)
        self.wait_for_cmd = self.convert_duration(wait_for_cmd)
        
    def __repr__(self):
        return "%s(host=%r,port=%r,dbhost=%r,dbport=%r,dbuser=%r,dbpassword=%r,dbname=%r,dbdrop=%r,stepsize=%r,mode=%r,number_of_steps=%r,time_delta=%r,wait_for_cmd=%r)" % \
            (self.__class__.__name__,
             self.host,self.port, 
             self.dbhost,self.dbport,self.dbuser,self.dbpassword,self.dbname,self.dbdrop,
             self.stepsize,self.mode,self.number_of_steps, self.time_delta,self.wait_for_cmd
             )
    @classmethod
    def convert_duration(self,val):
        pat = re.compile(r'([hmsd])')
        interval,unit,drop=pat.split(val)
        if unit == 's':
            return int(interval)
        elif unit == 'm':
            return int(interval)*60
        elif unit == 'h':
            return int(interval)*3600
        elif unit == 'd':
            return int(interval)*24*3600
        else:
            return None
    
    @classmethod
    def setup(cls):
        def constructor(loader, node) :
            fields = loader.construct_mapping(node)
            return Config(**fields)
        yaml.add_constructor('!DSSAConfig', constructor)
        

