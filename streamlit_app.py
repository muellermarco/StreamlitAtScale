import streamlit as st
from atscale.client import Client
from atscale.data_model import DataModel
from atscale.project import Project
import pandas as pd
import streamlit_theme as stt

stt.set_theme({'primary': '#1b3388'})

st.sidebar.image("AtScale_Logo.png")


st.title("Atscale API Demo")
#st.secrets["atscale_host"]
if 'client' not in st.session_state:
    st.session_state['client'] = Client(server=st.secrets["atscale_host"],
                    username=st.secrets["atscale_user"],
                    password=st.secrets["atscale_password"],
                    organization='default'
                )
if 'connected' not in st.session_state:
    st.session_state['client'].connect()
    st.session_state['connected'] = 1

#Sales Insights
if 'project' not in st.session_state:
    st.session_state['project'] = st.session_state['client'].select_project(published_project_id=st.secrets["atscale_project_id_published"],draft_project_id=st.secrets["atscale_project_id_draft"])
if 'data_model' not in st.session_state:    
    st.session_state['data_model'] = st.session_state['project'].select_data_model(st.secrets["atscale_model"])


if 'dimensions' not in st.session_state:
    dim_list = st.session_state['data_model'].get_features(st.session_state['data_model'].get_all_categorical_feature_names())    
    st.session_state['dimensions'] = {value['caption']:key  for key, value in dim_list.items()}
    #st.session_state['dimensions'] = pd.DataFrame(st.session_state['data_model'].get_all_categorical_feature_names())


if 'measures' not in st.session_state:
    measure_list = st.session_state['data_model'].get_features(st.session_state['data_model'].get_all_numeric_feature_names())
    st.session_state['measures'] =  {value['caption']:key  for key, value in measure_list.items()}
    #st.session_state['measures'] = pd.DataFrame(st.session_state['data_model'].get_all_numeric_feature_names())

#dim_list

#option = st.selectbox("wähle", feature_name_map)
#st.text(st.session_state['dimensions'][option])

#feature_name_map

selected_dimension = st.sidebar.selectbox('What Dimensions do you want to use?', st.session_state['dimensions'])

selected_measure = st.sidebar.selectbox('What Measures do you want to use?', st.session_state['measures'])

dynamic_data = st.session_state['data_model'].get_data(feature_list=[st.session_state['dimensions'][selected_dimension], st.session_state['measures'][selected_measure]], comment='Streamlit App by Marco Mueller')

st.bar_chart(data=dynamic_data, x=st.session_state['dimensions'][selected_dimension], y=st.session_state['measures'][selected_measure])