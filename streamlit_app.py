import streamlit as st
from atscale.client import Client
from atscale.data_model import DataModel
from atscale.project import Project

st.write("My first App")

#client = Client(server=st.secrets["atscale_host"],
#                username=st.secrets["atscale_user"],
#                password=st.secrets["atscale_password"],
#                organization='default'
#               )

#test = client.connect()
