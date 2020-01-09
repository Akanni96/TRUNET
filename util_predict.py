import tensorflow as tf
import pandas as pd
import models
import os
import pickle
import glob

def load_model(test_params, model_params):
    model = None

        # Option 2 - From checkpoint and model.py
   
    if(test_params['model_recover_method'] == 'checkpoint_batch'):
        
        model = models.SuperResolutionModel( test_params, model_params) 
        if type(model_params == list):
            model_params = model_params[0]

            #Just initliazing model so checkpoint method can work
        init_inp = tf.ones( [1, model_params['input_dims'][0],
                     model_params['input_dims'][1], model_params['conv1_inp_channels'] ] , dtype=tf.float32 )
        model(init_inp, pred=False )

        checkpoint_path = test_params['script_dir']+"/checkpoints/{}/batch/{}".format(model_params['model_name'], test_params['model_version'])

        ckpt = tf.train.Checkpoint(att_con=model)
        checkpoint_code = "B"+ str(tf.train.latest_checkpoint(checkpoint_path)[-5:])
        status = ckpt.restore( tf.train.latest_checkpoint(checkpoint_path) ).expect_partial()

        print("Are weights empty after restoring from checkpoint?", model.weights == [])
    
    elif(test_params['model_recover_method'] == 'checkpoint_epoch'):
        model = models.SuperResolutionModel( test_params, model_params)

        #Just initliazing model so checkpoint method can work
        if type(model_params == list):
            model_params = model_params[0]

        init_inp = tf.ones( [1, model_params['input_dims'][0],
                     model_params['input_dims'][1], model_params['conv1_inp_channels'] ] , dtype=tf.float32 )
        model(init_inp, pred=True )

        ckpt = tf.train.Checkpoint(att_con=model)

        #We will use Optimal Checkpoint information from checkpoint_scores_model.csv
        df_checkpoint_scores = pd.read_csv( test_params['script_dir']+'/checkpoints/{}/checkpoint_scores_model_{}.csv'.format(model_params['model_name'], test_params['model_version']), header=0 )
        best_checkpoint_path = df_checkpoint_scores['Checkpoint_Path'][0]
        checkpoint_code = "E"+str(df_checkpoint_scores['Epoch'][0])
        status = ckpt.restore( best_checkpoint_path ).expect_partial()

        print("Are weights empty after restoring from checkpoint?", model.weights == [] )

    return model, checkpoint_code

def save_preds( test_params, model_params, li_preds, li_timestamps, li_truevalues ):
    """
    
    """
    if type(model_params == list):
        model_params = model_params[0]

    _path_pred = test_params['script_dir'] + "/Output/{}/{}/Predictions".format(model_params['model_name'], test_params['model_version'])
    fn = str(li_timestamps[0][0]) + "___" + str(li_timestamps[-1][-1]) + ".dat"

    if(not os.path.exists(_path_pred) ):
        os.makedirs(_path_pred)
    
    li_preds = [ [ tens.numpy() for tens in _li ] for _li in li_preds ]
    li_truevalues = [ tens.numpy() for tens in li_truevalues]
    
    data_tuple = (li_timestamps, li_preds, li_truevalues)

    pickle.dump( data_tuple, open( _path_pred + "/" +fn ,"wb"), protocol=4 )
    print("Saved predictions\t", fn)

def load_predictions_gen(_path_pred):
    li_pred_fns = list( glob.glob(_path_pred+"/*") )
    for pred_fn in li_pred_fns:
        pred = pickle.load(open(pred_fn,"rb"))
        yield pred # list of lists; each sublist [ts, [stochastic preds], true] #shape ( x, [(width, hieght),.. ], (width, hieght) )