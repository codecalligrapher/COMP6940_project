import logging
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import credentials, firestore, initialize_app, db
from flask import Flask, request, jsonify
import numpy as np
from numpy import *
from soilparams import soil_params
from modelparams import pymc3_params, lr_params, ridge_params
import pickle

from datetime import date

cred = credentials.Certificate('../private/crop-jedi-storage-firebase-adminsdk-scef3-882ee18ae0.json')
app = firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://crop-jedi-storage-default-rtdb.firebaseio.com/'
})

class OrganiseData:
    '''
        Class meant to make call to firebase for stored data and return in usable formats for 
        regression calculation. filter_weather() is the only function intended to be used stand-alone
    '''
    def __init__(self,):
        pass

    def scale_weather(self, weather_data, recent_month=None):
        weather_data = self.filter_weather(weather_data, recent_month=recent_month)
        return weather_data

    def filter_weather(self, weather_data, recent_month=None):
        '''
            Calls backend database and filters based on current date and year
            Returns a tuple of filtered weather dictionary and a list of the keys to index the dictionary
            Dictionary is indexed by weather parameter (see weather keys) and dictionary contains lists of past values for each key 

        '''
        weather_filtered = dict()
        weather_keys = ['humidity_mean', 'humidity_var', 'pressure_mean', 'pressure_var', 'rain_mean', 'rain_var', 'temp', 'temp_max', 'temp_min']
        for weather_key in weather_keys:  
            month_current = int(date.today().strftime('%m'))
            if recent_month:  
                month_current = recent_month
            year_current = int(date.today().strftime('%Y'))
            temp_key_data = weather_data[0][weather_key]
            # To Store retrieved data
            temp_list = []
            for temp_data in temp_key_data.items():
                ## Gets most recent year        
                if int(temp_data[0][-6:-1])>= year_current-3:
                    temp_list.append(temp_data[1])

            weather_filtered[weather_key] = temp_list

        return weather_filtered, weather_keys

    def get_weather(self):
        '''
            Used to get raw weather data from firebase
        '''
        weather_ref = db.reference('weather_data')
        weather_data = weather_ref.get(weather_ref)
        return weather_data

    def get_soil(self):
        '''
            Used to get raw weather data from firebase
        '''
        soil_ref = db.reference('soil_data')
        soil_data = soil_ref.get(soil_ref)
        return soil_data


class RunSoilPrediction:
    '''
        Class pulls raw soil data from database and generates mean values for nitrogen, phosporous and potassium,
        mean values are then compared to optimal using l2 losses, and the crop with the minimum error is returned
    '''
    def __init__(self,):
        pass
    def predict_feasibility(self):
        organise_data = OrganiseData()
        soil_data = OrganiseData.get_soil()
        soil_series = self.gen_soil_series(soil_data)
        n_mean, p_mean, k_mean = self.get_mean_window(soil_series)

        errors = dict()

        errors['potato_error'] = self.calc_crop_error(soil_params['potato'], n_mean, p_mean, k_mean)
        errors['peas_error '] = self.calc_crop_error(soil_params['peas'], n_mean, p_mean, k_mean)
        errors['citrus_error'] = self.calc_crop_error(soil_params['citrus'], n_mean, p_mean, k_mean)

        return min(errors.items(), key=lambda x: x[1])


    def calc_crop_error(self, params, n_mean, p_mean, k_mean):
        '''
            Utility function for calculating loss
        '''
        n_error = params['N']['mean'] - n_mean
        k_error = params['K']['mean'] - k_mean
        p_error = params['P']['mean'] - k_mean
        return (n_error**2 + k_error**2 + p_error**2)**(1/2)


    def gen_soil_series(self, soil_data):  
        '''
            Creates dataframe from soil data and returns cleaned data
        '''  
        df = pd.DataFrame(colums=['date', 'N', 'P', 'K'])
        for data in soil_data.items():
            df = df.append({'date': data[0], 'N': data[1]['N'], 'P': data[1]['P'], 'K': data[1]['K']})

        df = self.remove_trend(df)
        df = self.remove_seasonality(df)        
        return df

    def get_mean_window(self,df):
        '''
            Calculates mean values for N, P, K for the past months of the current year and returns dictionary of values
        '''
        cur_month, cur_year = int(date.today().strftime('%m')), int(date.today().strftime('%Y'))
        df_year = df[df['date'] >= cur_year]
        n = df_year['N'].mean()
        p = df_year['P'].mean()
        k = df_year['K'].mean()

        return dict({'N': n, 'P': p, 'K':k})



    # TODO    
    def remove_trend(self, df):
        '''
            Utility function to remove trend from data
        '''
        return df
  
    def remove_seasonality(self, df):
        '''
            Utility function to remove trend from data
        '''
        return df


class RunPrediction:
    '''
        Class meant to determine the most optimal crop to be planted
    '''
    def __init__(self):
        self.model_params = None 


    def select_model(self, model_params):
        '''
            Sets model parameters for prediction
        '''
        self.model_params = model_params

    def predict_crop_feasibility(self, weather_data, model_params):
        '''
            Base function for calculating feasibility for ALL crops and returning scores
        '''
        if self.model_params is None:
            logging.warning("pymc3_params selected as default")
            self.model_params = pymc3_params

        potato_data = self._choose_crop(weather_data, crop='POTATO')
        citrus_data = self._choose_crop(weather_data, crop='CITRUS')
        peas_data = self._choose_crop(weather_data, crop='PEAS')
        
        potato = self._predict_crop_feasibility(potato_data, self.model_params['POTATO'])
        citrus = self._predict_crop_feasibility(citrus_data, self.model_params['CITRUS'])
        peas = self._predict_crop_feasibility(peas_data, self.model_params['PEAS'])

        divisor = max([potato, citrus, peas])
        potato /= divisor
        citrus /= divisor
        peas /= divisor

        return potato, citrus, peas

    def scale_weather_data(self, weather_filtered):
        '''
            Function takes weather data formatted into a dictionary of values,
            removes trend/seasonality using stationary differencing and scales using pre-baked
            scalers from training, this can then be used to generate crop optimality readings
        '''
        scalers = self.load_scalers()
        for weather in weather_filtered.items():
            # weather is a tuple, for example: ('humidity_mean', [array containing values for humidity_mean])
            label = weather[0]
            data = weather[1]
            for i in range(1, len(data) - 1):
                data[i+1] = data[i+1] - data[i]
            weather_filtered[label] = scalers[label].transform(np.array(data).reshape(-1,1))
            
        return weather_filtered

    def forecast_prediction(self, weather_filtered, weather_keys):
        '''
            # TODO: Take scaled data and calculate optimal values for each crop using three different models, returning 
            optimal crops for the past 6 months, generate 3-month and 6-month optimal forecast using this data for each of the 
            regression models (bayesian, linear, etc)
        '''
        scaled_data = self.scale_weather_data(weather_filtered)
        index = [i for i in range(len(scaled_data[weather_keys[0]]))]
        shortest_val = np.Inf
        for i in scaled_data.items():
            shortest_val = min(i[1].shape[0], shortest_val)
        scaled_df = pd.DataFrame(
            {
                weather_keys[0]: np.transpose(scaled_data[weather_keys[0]])[0][-shortest_val:],
                weather_keys[1]: np.transpose(scaled_data[weather_keys[1]])[0][-shortest_val:],
                weather_keys[2]: np.transpose(scaled_data[weather_keys[2]])[0][-shortest_val:],
                weather_keys[3]: np.transpose(scaled_data[weather_keys[3]])[0][-shortest_val:],
                weather_keys[4]: np.transpose(scaled_data[weather_keys[4]])[0][-shortest_val:],
                weather_keys[5]: np.transpose(scaled_data[weather_keys[5]])[0][-shortest_val:],
                weather_keys[6]: np.transpose(scaled_data[weather_keys[6]])[0][-shortest_val:],
                weather_keys[7]: np.transpose(scaled_data[weather_keys[7]])[0][-shortest_val:],
                weather_keys[8]: np.transpose(scaled_data[weather_keys[8]])[0][-shortest_val:],
                'peas': [-1]*shortest_val, 
                'citrus': [-1]*shortest_val, 
                'potato': [-1]*shortest_val, 
            },
            index = index
        )

        # Take output of predict_crop_feasibility and insert into each row depending on weather valueus
        # Do for each model, only change is parrams beingg paasseend
        # single-function call to do exponential forecasting on peas, citrus and potato columns for 3 and 6 months


        return scaled_df

    def _predict_crop_feasibility(self, crop, model_params):
        '''
            Base function for predicting feasibility of single crop given crop and model parameters
        '''
        crop_data, crop_keys = crop[0], crop[1]
        res = 0.0

        for crop_key in crop_keys:
            res += crop_data[crop_key] * model_params[crop_key]

        res+= model_params['intercept']
        return res

    def load_scalers(self):
        scalers = dict()
        scalers['humidity_mean'] = pickle.load(open('scalers/humidity_mean_scaler.pkl', 'rb'))
        scalers['humidity_var'] = pickle.load(open('scalers/humidity_var_scaler.pkl', 'rb'))
        scalers['pressure_mean'] = pickle.load(open('scalers/pressure_mean_scaler.pkl', 'rb'))
        scalers['pressure_var'] = pickle.load(open('scalers/pressure_var_scaler.pkl', 'rb'))
        scalers['rain_mean'] = pickle.load(open('scalers/rain_mean_scaler.pkl', 'rb'))
        scalers['rain_var'] = pickle.load(open('scalers/rain_var_scaler.pkl', 'rb'))
        scalers['temp'] = pickle.load(open('scalers/temp_scaler.pkl', 'rb'))
        scalers['temp_max'] = pickle.load(open('scalers/temp_max_scaler.pkl', 'rb'))
        scalers['temp_min'] = pickle.load(open('scalers/temp_min_scaler.pkl', 'rb'))
        return scalers

    def _choose_crop(self, weather_data, crop):
        '''
            Utility function to return data per crop
        '''

        data = dict()
        potato_keys = ['pressure_mean', 'temp_max']
        citrus_keys = ['rain_mean', 'pressure_mean', 'rain_var']
        peas_keys = ['temp_min', 'temp_max']

        if crop == 'POTATO':           
            data['pressure_mean'] = np.exp(np.mean(weather_filtered['pressure_mean']))
            data['temp_max'] = np.exp(np.mean(weather_filtered['temp_max']))

        if crop == 'CITRUS':
            data['rain_mean'] = rain_mean = np.exp(np.mean(weather_filtered['rain_mean']))
            data['pressure_mean'] = np.mean(weather_filtered['pressure_mean'])
            data['rain_var'] = np.mean(weather_filtered['rain_var'])

        if crop == 'PIGEON_PEA':            
            data['temp_min'] = np.exp(np.mean(weather_filtered['temp_min']))
            data['temp_min_raw'] = np.mean(weather_filtered['temp_min'])
            data['temp_max'] = np.mean(weather_filtered['temp_max'])

        return data, data.keys()

organisedata = OrganiseData()
weather_data = organisedata.get_weather()
weather_filtered, weather_keys = organisedata.filter_weather(weather_data)

runprediction = RunPrediction()
print(runprediction.forecast_prediction(weather_filtered, weather_keys))

# genseries = GenerateSeries()
# genseries.gen_prediction()