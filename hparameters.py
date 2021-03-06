import numpy as np
import math
import tensorflow as tf
from operator import itemgetter
import pandas as pd
from datetime import datetime
import pickle
from functools import reduce

class HParams():
    """Inheritable class for the parameter classes
        Example of how to use
        hparams = Hparams(**kwargs)
        params_dict = hparams() #dictionary containing parameters
    """    
    def __init__( self ,**kwargs ):  
        
        self._default_params(**kwargs)
        
        if( kwargs != None):
            self.params.update( kwargs)
    
    def __call__(self):
        return self.params
    
    def _default_params(self,**kwargs):
        self.params = {}

class MParams(HParams):
    """Class to be inherited by parameter classes which are designed to return
        parameters for models
    """    
    def __init__(self,**kwargs):
     
        # Parameters related the extraction of the 2D patches of data
        self.regiongrid_param_adjustment(**kwargs)

        super(MParams,self).__init__(**kwargs)
                 
    def regiongrid_param_adjustment(self, **kwargs):
        """Creates a 'region_grid_params' dictionary containing
            information on the sizes and location of patches to be extracted
        """        
        if not hasattr(self, 'params'):
            self.params = {}

        self.params.update(
            {'region_grid_params':{
                'outer_box_dims':[16,16],
                'inner_box_dims':[4,4],
                'vertical_shift':4,
                'horizontal_shift':4,
                'input_image_shape':[100,140]}
            }
        )
    
        vertical_slides = (self.params['region_grid_params']['input_image_shape'][0] - self.params['region_grid_params']['outer_box_dims'][0] +1 )// self.params['region_grid_params']['vertical_shift']
        horizontal_slides = (self.params['region_grid_params']['input_image_shape'][1] - self.params['region_grid_params']['outer_box_dims'][1] +1 ) // self.params['region_grid_params']['horizontal_shift']
        
        self.params['region_grid_params'].update({'slides_v_h':[vertical_slides, horizontal_slides]})

class model_TRUNET_hparameters(MParams):
    """Parameters Class for the TRUNET Encoder-Decoder model
    """
    def __init__(self, **kwargs):

        self.conv_ops_qk = kwargs['model_type_settings'].get('conv_ops_qk',False)
        kwargs['model_type_settings'].pop('conv_ops_qk',None)
        
        super( model_TRUNET_hparameters, self ).__init__(**kwargs)

    def _default_params( self, **kwargs ):
        
        model_type_settings = kwargs.get('model_type_settings', {})        

        # region --- learning / convergence / regularlisation params

        REC_ADAM_PARAMS = {
            "learning_rate":model_type_settings.get('lr_max',5e-4),   "warmup_proportion":0.65,
            "min_lr":model_type_settings.get('lr_min',5e-5),         "beta_1":model_type_settings.get('b1',0.9),               "beta_2":model_type_settings.get('b2',0.99),
            "amsgrad":True,         "decay":0.0008,              "epsilon":5e-8 } #Rectified Adam params  
        
        clip_norm = model_type_settings.get('clip_norm',5.5)

        DROPOUT =   model_type_settings.get('do',0.35)
        ido =       model_type_settings.get('ido',0.15) #model_type_settings.get('ido',0.35) # Dropout for input into GRU
        rdo =       model_type_settings.get('rdo',0.35) # Dropout for recurrent input into GRU
        kernel_reg   = None  #regularlization for input to GRU
        recurrent_reg = None #regularlization for recurrent input to GRU
        bias_reg = tf.keras.regularizers.l2(0.0)
        bias_reg_attn = tf.keras.regularizers.l2(0.0000)
        kernel_reg_attn = tf.keras.regularizers.l2(0.0000)
        # endregion

        # region --- Key Model Size Settings
        seq_len_for_highest_hierachy_level = 4 # Seq length of GRU operations in highest level of encoder

        seq_len_factor_reduction = [4, 7]   # This represents the reduction in seq_len when going from layer 1 
                                                #to layer 2 and layer 2 to layer 3 in the encoder / decoder
                                                    # 6hrs, 1Day, 1Week
        # endregion

        # region --- Model Specific Data Generating Params
        target_to_feature_time_ratio = seq_len_factor_reduction[0] 
        lookback_feature = reduce( (lambda x,y: x*y ), seq_len_factor_reduction ) * seq_len_for_highest_hierachy_level #Temporal length of input elements
        DATA_PIPELINE_PARAMS = {
            'lookback_feature':lookback_feature,
            'lookback_target': int(lookback_feature/target_to_feature_time_ratio) #Temporal length of output elements
        }
        # endregion
           
        # region --- ENCODER params 
        enc_layer_count        = len( seq_len_factor_reduction ) + 1
        attn_layers_count = enc_layer_count - 1

        # ConvGRU params
        filters = 64 #72  # no. of filters in all conv operations in ConvGRU units


        kernel_size_enc        = [ (4,4) ] * ( enc_layer_count )             
        print("Check appropriate stateful is being used for multi gpu status")
        stateful = False                       

        # Attention params
        attn_heads = [ model_type_settings.get('heads', 8) ]*attn_layers_count            
            #NOTE:Must be a factor of h or w or c. h,w are dependent on model type so make it a multiple of c = 8

        kq_downscale_stride = [1, 4, 4]            

        kq_downscale_kernelshape = kq_downscale_stride
        key_depth = [filters]*attn_layers_count # Key vector size
        val_depth = [ int( np.prod( self.params['region_grid_params']['outer_box_dims'] ) * filters * 2 )] *attn_layers_count
                  
        attn_layers_num_of_splits = list(reversed((np.cumprod( list( reversed(seq_len_factor_reduction[1:] + [1] ) ) ) *seq_len_for_highest_hierachy_level ).tolist())) 
            # attn_layers_num_of_splits is how many chunks the incoming tensors are split into

        attn_params_enc = [
            {'bias':None, 'total_key_depth': kd  ,'total_value_depth':vd, 'output_depth': vd   ,
            'num_heads': nh , 'dropout_rate':DROPOUT, 'value_dropout':model_type_settings.get('value_dropout',True),
            'max_relative_position':None, "transform_value_antecedent":True,  "transform_output":True, 
            'implementation':1, 'conv_ops_qk':self.conv_ops_qk,
            "value_conv":{ "filters":int(filters * 2), 'kernel_size':[3,3] ,'use_bias':True, "activation":'relu', 'name':"v", 'bias_regularizer':bias_reg_attn, 'kernel_regularizer':kernel_reg_attn ,'padding':'same' },
            "output_conv":{ "filters":int(filters * 2), 'kernel_size':[3,3] ,'use_bias':True, "activation":'relu', 'name':"outp", 'bias_regularizer':bias_reg_attn, 'kernel_regularizer':kernel_reg_attn, 'padding':'same' }
            } 
            for kd, vd ,nh, idx in zip( key_depth, val_depth, attn_heads,range(attn_layers_count) )
        ] #list of param dictionaries for each Inter Layer Cross Attention unit in the encoder
            #Note: bias refers to any attention masking, use_bias refers to bias used in convolutional ops

        attn_downscaling_params_enc = {
            'kq_downscale_stride': kq_downscale_stride,
            'kq_downscale_kernelshape':kq_downscale_kernelshape
        } #List of params for 3D average pooling operations
        
        CGRUs_params_enc = [
            {'filters':filters , 'kernel_size':ks, 'padding':'same', 
                'return_sequences':True, 'dropout':ido, 'recurrent_dropout':rdo,
                'stateful':stateful, 'recurrent_regularizer': recurrent_reg, 'kernel_regularizer':kernel_reg,
                'bias_regularizer':bias_reg, 'implementation':1 ,'layer_norm':None }
             for ks in kernel_size_enc
        ] #list of params for each ConvGRU layer in the Encoder
      
        ENCODER_PARAMS = {
            'enc_layer_count': enc_layer_count,
            'attn_layers_count': attn_layers_count,
            'CGRUs_params' : CGRUs_params_enc,
            'ATTN_params': attn_params_enc,
            'ATTN_DOWNSCALING_params_enc':attn_downscaling_params_enc,
            'seq_len_factor_reduction': seq_len_factor_reduction,
            'attn_layers_num_of_splits': attn_layers_num_of_splits,
            'dropout':DROPOUT
        }
        #endregion

        # region --- DECODER params 
        decoder_layer_count = enc_layer_count-2
                
        kernel_size_dec = kernel_size_enc[ 1:1+decoder_layer_count  ]           
                                              
        # Each decoder layer sends in values into the layer below. 
        CGRUs_params_dec = [
            {'filters':filters , 'kernel_size':ks, 'padding':'same', 
                'return_sequences':True, 'dropout':ido,
                'recurrent_dropout':rdo, 
                'kernel_regularizer':kernel_reg,
                'recurrent_regularizer': recurrent_reg,
                'bias_regularizer':bias_reg,
                'stateful':stateful,
                'implementation':1 ,'layer_norm':[ None, None ]  }
             for ks in kernel_size_dec ] #list of dictionaries containing params for each ConvGRU layer in decoder

        decoder_layers_num_of_splits = attn_layers_num_of_splits[:decoder_layer_count]
            #Each output from a decoder layer is split into n chunks the fed to n different nodes in the layer below. param above tracks teh value n for each dec layer
        seq_len_factor_expansion = seq_len_factor_reduction[-decoder_layer_count:]
        DECODER_PARAMS = {
            'decoder_layer_count': decoder_layer_count,
            'CGRUs_params' : CGRUs_params_dec,
            'seq_len_factor_expansion': seq_len_factor_expansion, #This is written in the correct order
            'seq_len': decoder_layers_num_of_splits,
            'attn_layer_no_splits':attn_layers_num_of_splits,
            'dropout':DROPOUT
        }
        # endregion

        # region --- OUTPUT_LAYER_PARAMS and Upscaling
        output_filters = [  int(  8*(((filters*2)/4)//8)), 1 ] 
        output_kernel_size = [ (3,3), (3,3) ] 
        activations = ['relu','linear']

        OUTPUT_LAYER_PARAMS = [ 
            { "filters":fs, "kernel_size":ks , "padding":"same", "activation":act }
                for fs, ks, act in zip( output_filters, output_kernel_size, activations )
        ]
        # endregion
        
        self.params.update( {
            'model_name':"TRUNET",
            'model_type_settings':model_type_settings,
            'htuning':model_type_settings.get('htuning',False),
            'htune_version':model_type_settings.get('htune_version',0),
            'encoder_params':ENCODER_PARAMS,
            'decoder_params':DECODER_PARAMS,
            'output_layer_params':OUTPUT_LAYER_PARAMS,
            'data_pipeline_params':DATA_PIPELINE_PARAMS,

            'rec_adam_params':REC_ADAM_PARAMS,
            'dropout':DROPOUT,
            'clip_norm':clip_norm ,

            "time_sequential": True            
            
            } )

class model_HCGRU_hparamaters(MParams):

    def __init__(self, **kwargs):
                
        super(model_HCGRU_hparamaters, self).__init__(**kwargs)
    
    def _default_params(self,**kwargs):
        model_type_settings = kwargs.get('model_type_settings', {})        

        dropout = model_type_settings.get('do',0.2)

        #region --- ConvLayers
        layer_count = 4 
        filters = 80
        print("Check appropriate stateful is being used for multi gpu status")
        stateful = False
        kernel_sizes = [[4,4]]*layer_count
        paddings = ['same']*layer_count
        return_sequences = [True]*layer_count
        input_dropout = [model_type_settings.get('ido',0.1) ]*layer_count #[0.0]*layer_count
        recurrent_dropout = [ model_type_settings.get('rdo',0.35)]*layer_count #[0.0]*layer_count

        ConvGRU_layer_params = [ { 'filters':filters, 'kernel_size':ks , 'padding': ps,
                                'return_sequences':rs, "dropout": dp , "recurrent_dropout":rdp,
                                'kernel_regularizer': None,
                                'recurrent_regularizer': None,
                                'bias_regularizer':tf.keras.regularizers.l2(0.0),
                                'layer_norm': None,
                                'implementation':1, 'stateful':stateful  }
                                for ks,ps,rs,dp,rdp in zip( kernel_sizes, paddings, return_sequences, input_dropout, recurrent_dropout)  ]

        conv1_layer_params = {'filters': int(  8*(((filters*2)/3)//8)) , 'kernel_size':[3,3], 'activation':'relu','padding':'same','bias_regularizer':tf.keras.regularizers.l2(0.0) }  

        outpconv_layer_params = {'filters':1, 'kernel_size':[3,3], 'activation':'linear','padding':'same','bias_regularizer':tf.keras.regularizers.l2(0.0) }
        #endregion

        #region --- Data pipeline and optimizers
        target_to_feature_time_ratio = 4
        lookback_feature = 28*target_to_feature_time_ratio  
        DATA_PIPELINE_PARAMS = {
            'lookback_feature':lookback_feature,
            'lookback_target': int(lookback_feature/target_to_feature_time_ratio),
            'target_to_feature_time_ratio' :  target_to_feature_time_ratio
        }


        REC_ADAM_PARAMS = {
            "learning_rate":model_type_settings.get('lr_max',1e-3),
            "warmup_proportion":0.65,
            "min_lr":model_type_settings.get('lr_min',1e-4),
            "beta_1":model_type_settings.get('b1',0.75),  
            "beta_2":model_type_settings.get( 'b2',0.99),
            "amsgrad":True,
            "decay":0.0008,
            "epsilon":5e-8 } #Rectified Adam params
        
        LOOKAHEAD_PARAMS = { "sync_period":1 , "slow_step_size":0.99 }

        # endregion
        model_type_settings = kwargs.get('model_type_settings',{})

        self.params.update( {
            'model_name':'HCGRU',
            'layer_count':layer_count,
            'ConvGRU_layer_params':ConvGRU_layer_params,
            'conv1_layer_params':conv1_layer_params,
            'outpconv_layer_params': outpconv_layer_params,
            'dropout': dropout,

            'data_pipeline_params':DATA_PIPELINE_PARAMS,
            'model_type_settings':model_type_settings,
            'htuning':model_type_settings.get('htuning',False),
            'htune_version':model_type_settings.get('htune_version',0),
            'rec_adam_params':REC_ADAM_PARAMS,
            'lookahead_params':LOOKAHEAD_PARAMS,
            'clip_norm':model_type_settings.get('clip_norm',5.5),
            "time_sequential": True
        })

class model_UNET_hparamaters(MParams):

    def __init__(self, **kwargs):       
        super(model_UNET_hparamaters, self).__init__(**kwargs)
    
    def _default_params(self,**kwargs):
        model_type_settings = kwargs.get( 'model_type_settings', {} )        
        dropout = model_type_settings.get('do',0.01)

        

        REC_ADAM_PARAMS = {
            "learning_rate":model_type_settings.get('lr_max',1e-4),
            "warmup_proportion":0.65,
            "min_lr":model_type_settings.get('lr_min',1e-5),
            "amsgrad":True,
            "decay":0.0008,
            "epsilon":1e-5 } #Rectified Adam params
        
        LOOKAHEAD_PARAMS = { "sync_period":1 , "slow_step_size":0.99 }

        
        model_type_settings = kwargs.get( 'model_type_settings', {} )

        self.params.update( {
            'model_name':'UNET',
            'dropout': dropout,
            
            'model_type_settings':model_type_settings,

            'rec_adam_params':REC_ADAM_PARAMS,
            'lookahead_params':LOOKAHEAD_PARAMS,
            'clip_norm':model_type_settings.get('clip_norm',5.0 ),

            "time_sequential": False
        })

class train_hparameters_ati(HParams):
    """ Parameters for testing """
    def __init__(self, **kwargs):
        self.lookback_target = kwargs.pop('lookback_target',1)
        self.batch_size = kwargs.pop('batch_size')
        self.dd = kwargs.get("data_dir",'./Data/Rain_Data_Mar20') 
        self.objective = kwargs.get("objective","mse")
        self.parallel_calls = kwargs.get("parallel_calls",-1)
        self.epochs = kwargs.get("epochs",100)
        
        # data formulation method
        self.custom_train_split_method = kwargs.get('ctsm') 
            
        if self.custom_train_split_method == "4ds_10years":
            self.four_year_idx_train = kwargs['fyi_train'] #index for training set

    
        
        
        
        super( train_hparameters_ati, self).__init__(**kwargs)

    def _default_params(self, **kwargs):
        # region ------- Masking, Standardisation, temporal_data_size
        trainable = True
        MASK_FILL_VALUE = {
                                    "rain":0.0,
                                    "model_field":0.0 
        }
        vars_for_feature = ['unknown_local_param_137_128', 'unknown_local_param_133_128', 'air_temperature', 'geopotential', 'x_wind', 'y_wind' ]
        NORMALIZATION_SCALES = {
                                    "rain":4.69872+0.5,
                                    "model_fields": np.array([6.805,
                                                              0.001786,
                                                              5.458,
                                                              1678.2178,
                                                                5.107268,
                                                                4.764533]) }
        NORMALIZATION_SHIFT = {
                                    "rain":2.844,
                                    "model_fields": np.array([15.442,
                                                                0.003758,
                                                                274.833,
                                                                54309.66,
                                                                3.08158,
                                                                0.54810]) 
        }
        WINDOW_SHIFT = self.lookback_target
        BATCH_SIZE = self.batch_size
        # endregion

        EPOCHS = self.epochs
        CHECKPOINTS_TO_KEEP = 1

        # region ---- data formulation strategies
        target_start_date = np.datetime64('1950-01-01') + np.timedelta64(10592,'D')
        feature_start_date = np.datetime64('1970-01-01') + np.timedelta64(78888, 'h')

                # a string containing four dates seperated by underscores
        # The numbers correspond to trainstart_trainend_valstart_valend

        dates_str = self.custom_train_split_method.split("_")
        start_date = np.datetime64(dates_str[0],'D')
        train_end_date = (pd.Timestamp(dates_str[1]) - pd.DateOffset(seconds=1) ).to_numpy()
        val_start_date = np.datetime64(dates_str[1],'D')
        val_end_date = (pd.Timestamp(dates_str[2]) - pd.DateOffset(seconds=1) ).to_numpy()
        
        TRAIN_SET_SIZE_ELEMENTS = ( np.timedelta64(train_end_date - start_date,'D')).astype(int)  // WINDOW_SHIFT  
        VAL_SET_SIZE_ELEMENTS   = ( np.timedelta64(val_end_date - val_start_date,'D')  // WINDOW_SHIFT  ).astype(int)               
        
        # endregion
        
        DATA_DIR = self.dd
        EARLY_STOPPING_PERIOD = 25
 
        self.params = {
            'batch_size':BATCH_SIZE,
            'epochs':EPOCHS,
            'early_stopping_period':EARLY_STOPPING_PERIOD,
            'trainable':trainable,
            'lookback_target':self.lookback_target,

            'train_batches': TRAIN_SET_SIZE_ELEMENTS//BATCH_SIZE, 
                #Note TRAIN_SET_SIZE_ELEMENTS refers to the number of sequences of days that are passed to TRU_NET as oppose dot every single day
            'val_batches': VAL_SET_SIZE_ELEMENTS//BATCH_SIZE,

            'checkpoints_to_keep':CHECKPOINTS_TO_KEEP,
            'reporting_freq':0.25,

            'train_monte_carlo_samples':1,
            'data_dir': DATA_DIR,
            
            'mask_fill_value':MASK_FILL_VALUE,
            'vars_for_feature':vars_for_feature,
            'normalization_scales' : NORMALIZATION_SCALES,
            'normalization_shift': NORMALIZATION_SHIFT,
            'window_shift': WINDOW_SHIFT,

            'start_date':start_date,
            'val_start_date':val_start_date,
            'val_end_date':val_end_date,

            'feature_start_date':feature_start_date,
            'target_start_date':target_start_date,
            'objective':self.objective,
            'parallel_calls':self.parallel_calls
        }

class test_hparameters_ati(HParams):
    """ Parameters for testing """
    def __init__(self, **kwargs):
        self.lookback_target = kwargs['lookback_target']
        self.batch_size = kwargs.get("batch_size", 2)
        self.parallel_calls = kwargs.get('parallel_calls', -1)

        self.dd = kwargs.get('data_dir')
        self.custom_test_split_method = kwargs.get('ctsm_test')
        
        if self.custom_test_split_method == "4ds_10years":
            self.four_year_idx_train = kwargs['fyi_train'] #index for training set
            self.four_year_idx_test = kwargs['fyi_test']
            assert self.four_year_idx_train != self.four_year_idx_test

        super( test_hparameters_ati, self).__init__(**kwargs)
    
    def _default_params(self, **kwargs):
        
        # region --- data pipepline vars
        trainable = False

        # Standardisation and masking variables
        MASK_FILL_VALUE = {
                                    "rain":0.0,
                                    "model_field":0.0 
        }
        vars_for_feature = ['unknown_local_param_137_128', 'unknown_local_param_133_128', 'air_temperature', 'geopotential', 'x_wind', 'y_wind' ]
        NORMALIZATION_SCALES = {
                                    "rain":4.69872+0.5,
                                    "model_fields": np.array([6.805,
                                                              0.001786,
                                                              5.458,
                                                              1678.2178,
                                                                5.107268,
                                                                4.764533]) 
                                                #- unknown_local_param_137_128
                                                # - unknown_local_param_133_128,  
                                                # # - air_temperature, 
                                                # # - geopotential
                                                # - x_wind, 
                                                # # - y_wind
        }
        NORMALIZATION_SHIFT = {
                                    "rain":2.844,
                                    "model_fields": np.array([15.442,
                                                                0.003758,
                                                                274.833,
                                                                54309.66,
                                                                3.08158,
                                                                0.54810]) 
        }

        
        WINDOW_SHIFT = self.lookback_target # temporal shift for window to evaluate
        BATCH_SIZE = self.batch_size
        # endregion

        # region ---- Data Formaulation

        target_start_date = np.datetime64('1950-01-01') + np.timedelta64(10592,'D') #E-obs recording start from 1950
        feature_start_date = np.datetime64('1970-01-01') + np.timedelta64(78888, 'h') #ERA5 recording start from 1979
        
        tar_end_date =  target_start_date + np.timedelta64( 14822, 'D')
        feature_end_date  = np.datetime64( feature_start_date + np.timedelta64(59900, '6h'), 'D')
        
        start_date = feature_start_date if (feature_start_date > target_start_date) else target_start_date
        end_date = tar_end_date if (tar_end_date < feature_end_date) else feature_end_date     

        # User must pass in two dates seperated by underscore such as 
        dates_str = self.custom_test_split_method.split("_")
        start_date = np.datetime64(dates_str[0],'D')
        test_end_date = (pd.Timestamp(dates_str[1]) - pd.DateOffset(seconds=1) ).to_numpy()

        TEST_SET_SIZE_DAYS_TARGET = np.timedelta64( test_end_date - start_date, 'D' ).astype(int)
        # endregion

        # timesteps for saving predictions
        date_tss = pd.date_range( end=test_end_date, start=start_date, freq='D', normalize=True)
        timestamps = list ( (date_tss - pd.Timestamp("1970-01-01") ) // pd.Timedelta('1s') )

        DATA_DIR = self.dd

        self.params = {
            'batch_size':BATCH_SIZE,
            'trainable':trainable,
            
            'test_batches': TEST_SET_SIZE_DAYS_TARGET//(WINDOW_SHIFT*BATCH_SIZE),
                        
            'script_dir':None,
            'data_dir':DATA_DIR,
            
            'timestamps':timestamps,
            
            'mask_fill_value':MASK_FILL_VALUE,
            'vars_for_feature':vars_for_feature,
            'normalization_scales' : NORMALIZATION_SCALES,
            'normalization_shift': NORMALIZATION_SHIFT,
            'window_shift': WINDOW_SHIFT,

            'start_date':start_date,
            'test_end_date':test_end_date,

            'feature_start_date':feature_start_date,
            'target_start_date':target_start_date,
            'parallel_calls':self.parallel_calls

        }
