'''
   File contains imports for firebase realtime database, loads secure credentials and initialises a 
   firebase app for which database connections can be added afterwards 
'''
import firebase_admin
from firebase_admin import credentials
from firebase_admin import credentials, firestore, initialize_app, db
from flask import Flask, request, jsonify


cred = credentials.Certificate('private/crop-jedi-storage-firebase-adminsdk-scef3-882ee18ae0.json')
app = firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://crop-jedi-storage-default-rtdb.firebaseio.com/'
})
