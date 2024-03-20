import streamlit as st
from atscale.client import Client
from atscale.data_model import DataModel
from atscale.project import Project

st.write("My first App")

client = Client(server=st.secrets["atscale_host"],
                username="asdf",
                password="",
                organization='default'
               )

test = client.connect()
st.write(test)