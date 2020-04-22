# -*- coding: utf-8 -*-
"""
Created on Sat Apr 11 21:22:25 2020

@author: ghoshp
"""

import tkinter as tk
from tkinter import messagebox
from tkinter.filedialog import askopenfilename
import os
from dssa.agent import Agent
import traceback
import threading
#from threading import RLock
from queue import Queue
import time

class guiclient():
    def __init__(self):
        self.app_base = ""
        self.app_path = ""
        self.pause_flag = False
        self.stop_flag = True
        self.dssgui = tk.Tk()
        self.dssgui.title("OpenDSS Agent Launcher")
        self.dssgui.sim_dir = ""
        self.errorout= Queue()
        
        self.greeting = tk.Label(master = self.dssgui, 
                                 text= "OpenDSS Client for RIAPS", background = "orange")
        self.greeting.grid(row=0,columnspan = 3,sticky = "ew")
        
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
       

    def select_file(self):
        self.dssgui.sim_dir = askopenfilename(initialdir=os.getcwd(), title="Select simulation file",
                                           filetypes=(("dss files","*.dss"),("all files","*.*")))
        self.app_path = os.path.dirname(self.dssgui.sim_dir)
        model_name = os.path.basename(self.dssgui.sim_dir)
        self.app_base = model_name.split('.')[0]
        self.file_label['text']= self.dssgui.sim_dir
        
    def handle_start(self):
        
        if not self.stop_flag:
            messagebox.showinfo("Info", "Stop current simulation")
        elif self.app_path == "":
            messagebox.showinfo("Info", "Select file to run")
        else:
            self.stop_flag = False
            self.sim_thread = SimulationThread(self.app_path, self.app_base, self.errorout)
            self.sim_thread.start()
            self.popupthread = threading.Thread(target=self.window_popup)
            self.popupthread.start()
            print('starting simulation...')
        
    def handle_stop(self):
        if not self.stop_flag:
            self.stop_flag = True
            self.popupthread.join()
            self.errorout.queue.clear()
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
        
    def window_popup(self):
        while not self.stop_flag:
            if self.errorout.empty():
                time.sleep(.5)
            else:
                errstring = self.errorout.get()
                messagebox.showerror("Error", errstring)
                break
            
        
class SimulationThread(threading.Thread):
    def __init__(self, folder_path, app_base, simerrorout):
        threading.Thread.__init__(self)
        self.theAgent = None
        self.folder_path = folder_path
        self.app_base = app_base
        self.simerrorout= simerrorout
        
        
    def run(self):
        try:
            os.chdir(self.folder_path)
            self.theAgent = Agent(self.app_base, self.folder_path, self.simerrorout)
            self.theAgent.start()       
            self.theAgent.run()       
        except Exception:
            self.simerrorout.put(traceback.format_exc())
            if self.theAgent != None: self.theAgent.stop()
        
    def pause_resume_sim(self, pause_flag):
        self.theAgent.handle_pause(pause_flag)
        
    def cleanup(self):
        if self.theAgent != None: self.theAgent.stop()

        
if __name__ == '__main__':
    dssa_gui = guiclient()