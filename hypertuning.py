#from netCDF4 import Dataset, num2date
import os
# os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
# os.environ['TF_FORCE_GPU_ALLOW_GROWTH'] = 'true'
import argparse
import ast
import gc
import logging
import math

import sys
import time

import numpy as np
import pandas as pd
#import psutil

#import tensorflow as tf
#from tensorflow.keras.mixed_precision import experimental as mixed_precision

# try:
#     import tensorflow_addons as tfa
# except Exception as e:
#     tfa = None

# import data_generators
# import custom_losses as cl
import hparameters
# import models
import utility

 
def main(m_params):

    #defining hyperam range
    if m_params['model_name'] == "SimpleConvGRU" :
        # Rectified Adam Parameters
        lrs_max_min = [ (1e-3, 1e-4), (1e-4,1e-5)] # minimum and maximum learning rate
        b1s = [0.75, 0.9]                            # beta 1
        b2s = [0.9, 0.99]                                 # beta 2
        
        inp_dropouts = [0.1, 0.225, 0.35]                #input dropout
        rec_dropouts = [0.1, 0.225, 0.35]             #recurrent dropout
        clip_norms = [12.5]

        counter =  0

        os.makedirs('hypertune',exist_ok=True)
        f_training =  open(f"hypertune/{m_params['model_name']}_train.txt","w")
        # f_training2 =  open("hypertune/hypertune_train2.txt","w")
        
        f_testings =  [ open(f"hypertune/{m_params['model_name']}_test_{idx+1}.txt","w") for idx in range(3) ]

        for lr in lrs_max_min:
            for b1 in b1s:
                for b2 in b2s:
                    for inpd in inp_dropouts:
                        for recd in rec_dropouts:

                            print(f"\n\n Training model v{counter}")
                            train_cmd = train_cmd_maker( m_params['model_name'], lr, b1, b2, inpd, recd, counter )
                            f_training.write(f'{train_cmd} && ')

                            print(f" Testing model v{counter}")
                            test_cmd = test_cmd_maker( m_params['model_name'], inpd, recd, counter )
                            #f_testing.write(f'{train_cmd} && ')
                            f_testings[int(counter%3)].write(f'{test_cmd} && ')
                            
                            counter = counter + 1
        f_training.close()
        [ f.close() for f in f_testings ]
    
    elif m_params['model_name'] == "TRUNET":

        # Rectified Adam Parameters
        lrs_max_min = [ (1e-3, 1e-4)] # minimum and maximum learning rate
        b1s = [0.75, 0.9]                            # beta 1
        b2s = [0.9, 0.99]                                 # beta 2
        
        dropouts = [0.15, 0.35 ]
        inp_dropouts = [0.1, 0.225, 0.35]                #input dropout
        rec_dropouts = [0.1, 0.225, 0.35]             #recurrent dropout
        clip_norms = [6.5, 12.5]

        counter =  0

        os.makedirs('hypertune',exist_ok=True)
        f_training =  open(f"hypertune/{m_params['model_name']}_train.txt","w")
        # f_training2 =  open("hypertune/hypertune_train2.txt","w")
        
        f_testings =  [ open(f"hypertune/{m_params['model_name']}_test_{idx+1}.txt","w") for idx in range(3) ]

        for lr in lrs_max_min:
            for b1 in b1s:
                for b2 in b2s:
                    for inpd in inp_dropouts:
                        for recd in rec_dropouts:
                            for clip_norm in clip_norms:
                                for dropout in dropouts:

                                    print(f"\n\n Training model v{counter}")
                                    train_cmd = train_cmd_maker( m_params['model_name'], lr, b1, b2, inpd, recd, counter, clip_norm=clip_norm, do=dropout )
                                    f_training.write(f'{train_cmd} && ')

                                    print(f" Testing model v{counter}")
                                    test_cmd = test_cmd_maker( m_params['model_name'], inpd, recd, counter, dropout )
                                    #f_testing.write(f'{train_cmd} && ')
                                    f_testings[int(counter%3)].write(f'{test_cmd} && ')
                                    
                                    counter = counter + 1
        f_training.close()
        [ f.close() for f in f_testings ]



def train_cmd_maker( mn ,lr_min_max, b1, b2, inp_drop, rec_drop, counter,gpu=None,clip_norm=6.5, do=0.2):
    cmd = [
        f"CUDA_VISIBLE_DEVICES=0",
        # f"CUDA_VISIBLE_DEVICES={gpu}",
        "python3", "train.py","-mn",f"{mn}",
        "-ctsm", "1999_2009_2014", "-mts",
        f"\"{{'htuning':True, 'htune_version':{counter},'stochastic':False,'stochastic_f_pass':1,'clip_norm':{clip_norm},'discrete_continuous':True,'var_model_type':'mc_dropout','do':{do},'ido':{inp_drop},'rdo':{rec_drop}, 'b1':{b1}, 'b2':{b2}, 'lr_max':{lr_min_max[0]}, 'lr_min':{lr_min_max[1]}, 'location':['Cardiff','London','Glasgow','Birmingham','Lancaster','Manchester','Liverpool','Bradford','Edinburgh','Leeds'] }}\"",
        "-dd", "/media/Data3/akanni/Rain_Data_Mar20", "-bs", "16"]
    
    cmd2 = ' '.join(cmd)
    return cmd2

def test_cmd_maker( mn,inp_drop, rec_drop, counter, do=0.2):
    cmd = [ 
        f"CUDA_VISIBLE_DEVICES={int(counter%3)+1}",
        "python3", "predict.py", "-mn", f"{mn}", "-ctsm", "1999_2009_2014", "-ctsm_test", "2014_2019-07-04", "-mts",
    f"\"{{'htuning':True,'htune_version':{counter},'stochastic':True,'stochastic_f_pass':5,'distr_type':'Normal','discrete_continuous':True,'var_model_type':'mc_dropout', 'do':{do},'ido':{inp_drop},'rdo':{rec_drop}, 'location':['Cardiff','London','Glasgow','Birmingham','Lancaster','Manchester','Liverpool','Bradford','Edinburgh','Leeds'],'location_test':['Cardiff','London','Glasgow','Birmingham','Lancaster','Manchester','Liverpool','Bradford','Edinburgh','Leeds']}}\"",
    "-ts", f"\"{{'region_pred':True}}\"", "-dd", "/media/Data3/akanni/Rain_Data_Mar20", "-bs", f"{65}" ]

    cmd2 = ' '.join(cmd)
    return cmd2
    

if __name__ == "__main__":
    s_dir = utility.get_script_directory(sys.argv[0])
    args_dict = utility.parse_arguments(s_dir)
    
    main( args_dict )

    #python3 hypertuning.py -mn "SimpleConvGRU" -mts "{}" -ctsm ""    
    #python3 hypertuning.py -mn "TRUNET" -mts "{}" -ctsm ""    
