# -*- coding: utf-8 -*-
"""
Created on Sat Apr 11 21:22:25 2020

@author: ghoshp
"""

import tkinter as tk
from tkinter.filedialog import askopenfilename, askdirectory
import os
from dssa.agent import Agent
import traceback
import threading

class guiclient():
    def __init__(self):
        self.app_base = ""
        self.app_path = ""
        self.pause_flag = False
        self.dssgui = tk.Tk()
        self.dssgui.title("OpenDSS Agent Launcher")
        self.dssgui.sim_dir = ""
        self.dssgui.app_dir = ""
        
        self.greeting = tk.Label(master = self.dssgui, 
                                 text= "OpenDSS Client for RIAPS", background = "orange")
        self.greeting.grid(row=0,columnspan = 3,sticky = "ew")
        
        self.folder_btn = tk.Button(master = self.dssgui, text="Folder",
                                  height=2, width = 5, command=self.select_folder)
        self.folder_btn.grid(row=1,column=0,sticky = "w")
        self.folder_label = tk.Label(master = self.dssgui, text= self.dssgui.app_dir,
                                     bg = "white",anchor ='w')
        self.folder_label.grid(row=1,column=1,columnspan = 2, sticky = "ew")
        
        self.file_btn = tk.Button(master = self.dssgui, text="Model",
                                  height=2, width = 5, command=self.select_file)
        self.file_btn.grid(row=2,column=0,sticky = "w")
        self.file_label = tk.Label(master = self.dssgui, text= self.dssgui.sim_dir,
                                   bg="white", anchor ='w')
        self.file_label.grid(row=2,column=1,columnspan = 2,sticky = "ew")
        
        self.simctrl_frame = tk.Frame(master = self.dssgui, padx = 20, pady = 10)
        self.simctrl_frame.grid(row=3, columnspan = 3)
        
        self.start_btn = tk.Button(master = self.simctrl_frame, text="Start",
                                  height=2, width = 5,
                                  padx=5,command=self.handle_start, bg = 'lime')
        self.start_btn.grid(row=0,column=0)
        
        self.pause_btn = tk.Button(self.simctrl_frame, text="Pause/\n Resume",
                                  height=2, width = 5,
                                  padx=5,command=self.handle_pause_resume, bg = 'yellow')
        self.pause_btn.grid(row=0,column=1)
        
        self.stop_btn = tk.Button(master = self.simctrl_frame, text="Stop",
                                  height=2, width = 5, 
                                  padx=5, command=self.handle_stop, bg = 'red')
        self.stop_btn.grid(row=0,column=2)
        
        
        self.dssgui.mainloop()
        
    def select_folder(self):
        self.dssgui.app_dir = askdirectory(initialdir="C:/", title="Select simulation file")
        self.folder_label['text']=self.dssgui.app_dir
        
    def select_file(self):
        self.dssgui.sim_dir = askopenfilename(initialdir=self.dssgui.app_dir, title="Select simulation file",
                                           filetypes=(("dss files","*.dss"),("all files","*.*")))
        model_name = os.path.basename(self.dssgui.sim_dir)
        self.file_label['text']= model_name
        
    def handle_start(self):
        app_base = self.file_label['text'].split('.')[0]
        self.sim_thread = SimulationThread(self.folder_label['text'], app_base)
        self.sim_thread.start()
        print('starting simulation...')
        
    def handle_stop(self):
        self.sim_thread.cleanup() 
        self.sim_thread.join()
        print("simulation stopped")
        
    def handle_pause_resume(self):
        self.pause_flag = not self.pause_flag
        if self.pause_flag:
            print("pausing simulation")
        else:
            print("resuming simulation")
        self.sim_thread.pause_resume_sim(self.pause_flag)
        
class SimulationThread(threading.Thread):
    def __init__(self, folder_path, app_base):
        threading.Thread.__init__(self)
        self.theAgent = None
        self.folder_path = folder_path
        self.app_base = app_base
        
        
    def run(self):
        try:
            os.chdir(self.folder_path)
            self.theAgent = Agent(self.app_base, self.folder_path)
            self.theAgent.start()       
            self.theAgent.run()       
        except Exception:
            traceback.print_exc()
            if self.theAgent != None: self.theAgent.stop()
        
    def pause_resume_sim(self, pause_flag):
        self.theAgent.handle_pause(pause_flag)
        
    def cleanup(self):
        self.theAgent.stop()
        
if __name__ == '__main__':
    dssa_gui = guiclient()