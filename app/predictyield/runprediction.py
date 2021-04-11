import logging
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import credentials, firestore, initialize_app, db
from flask import Flask, request, jsonify
import numpy as np
from soilparams import soil_params
from modelparams import pymc3_params, lr_params, ridge_params

from datetime import date

cred = credentials.Certificate('../private/HIDDEN.json')
app = firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://crop-jedi-storage-default-rtdb.firebaseio.com/'
})

class OrganiseData:
    def __init__(self,):
        pass

    def filter_weather(self, weather_data, recent_month=None):
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
        weather_ref = db.reference('weather_data')
        weather_data = weather_ref.get(weather_ref)
        return weather_data

    def get_soil(self):
        soil_ref = db.reference('soil_data')
        soil_data = soil_ref.get(soil_ref)
        return soil_data


class GenerateSeries: 
    def __init__(self):
        pass
    # TODO Figure out how far ahead the prediction should run, and if we can do this using predicted weather data from the pi
    def gen_prediction(self, current_month=6 ):
        organisedata = OrganiseData()
        weather_data = organisedata.get_weather()
        for month in range(current_month, current_month - 3, -1):
            weather_filtered, weather_keys = organisedata.filter_weather(weather_data, recent_month=current_month)

            runprediction = RunPrediction()
            pred = runprediction.predict_feasibility(weather_filtered)
            print(pred)


class RunSoilPrediction:
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
        n_error = params['N']['mean'] - n_mean
        k_error = params['K']['mean'] - k_mean
        p_error = params['P']['mean'] - k_mean
        return (n_error**2 + k_error**2 + p_error**2)**(1/2)


    def gen_soil_series(self, soil_data) -> pd.DataFrame:
        df = pd.DataFrame(colums=['date', 'N', 'P', 'K'])
        for data in soil_data.items():
            df = df.append({'date': data[0], 'N': data[1]['N'], 'P': data[1]['P'], 'K': data[1]['K']})

        df = self.remove_trend(df)
        df = self.remove_seasonality(df)        
        return df

    def get_mean_window(self,df):
        cur_month, cur_year = int(date.today().strftime('%m')), int(date.today().strftime('%Y'))
        df_year = df[df['date'] >= cur_year]
        n = df_year['N'].mean()
        p = df_year['P'].mean()
        k = df_year['K'].mean()

        return dict({'N': n, 'P': p, 'K':k})

    # TODO    
    def remove_trend(self, df):
        return df
  
    def remove_seasonality(self, df):
        return df


class RunPrediction:
    def __init__(self):
        self.model_params = None 

    def predict_feasibility(self, weather_data):        
        return self.predict_crop_feasibility(weather_data, pymc3_params)

    def select_model(self, model_params):
        self.model_params = model_params

    def predict_crop_feasibility(self, weather_data, model_params):
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


    def _predict_crop_feasibility(self, crop, model_params):
        crop_data, crop_keys = crop[0], crop[1]
        res = 0.0

        for crop_key in crop_keys:
            res += crop_data[crop_key] * model_params[crop_key]

        res+= model_params['intercept']
        return res

    def _choose_crop(self, weather_data, crop):
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
runprediction.predict_feasibility(weather_filtered)

genseries = GenerateSeries()
genseries.gen_prediction()