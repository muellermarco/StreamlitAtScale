import streamlit as st
from atscale.client import Client
from atscale.data_model import DataModel
from atscale.project import Project

st.write("My first App")

client = Client(server=st.secrets["atscale_host"],
                username=st.secrets["atscale_user"],
                password=st.secrets["atscale_password"],
                organization='default'
               )

test = client.connect()

#Sales Insights
project:Project = client.select_project(published_project_id='3d965074-0e49-42df-4151-74541f019bd0',draft_project_id='2e0203d7-fa65-4c28-7b65-357eb4aee0ea')
data_model = project.select_data_model("b89a2fb7-74f4-4828-706e-70f7186e10a0")

features_cat = data_model.get_all_categorical_feature_names()

st.write(features_cat)
