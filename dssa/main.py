'''
Created on Feb 2, 2020

@author: ghoshp
'''
import sys
import os
import argparse
import traceback
import signal

from dssa.agent import Agent

theAgent = None
conf = None

def termHandler(_signal,_frame):
    global theAgent
    theAgent.stop()
    
####################

def main(debug=True):
    parser = argparse.ArgumentParser(description="OpenDSS agent")
    parser.add_argument("path",help="path to model directory")
    parser.add_argument("name",help="base name for .dss, .dsl files")
    args = parser.parse_args()
        
    signal.signal(signal.SIGTERM,termHandler)
    signal.signal(signal.SIGINT,termHandler)
    
    global theAgent
    try:
        os.chdir(args.path)
        theAgent = Agent(args.name, args.path)
        theAgent.start()       
        theAgent.run()       
        theAgent.stop()
    except Exception:
        traceback.print_exc()
        if theAgent != None: theAgent.stop()
    #print ("Unexpected error:", sys.exc_info()[0])
    sys.exit()
    
if __name__ == '__main__':
    main()