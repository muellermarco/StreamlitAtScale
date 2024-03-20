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
st.write(test)

"""
#Sales Insights
project:Project = client.select_project(published_project_id='53d49296-e7d1-4a35-5f49-5621175219d9',draft_project_id='985a44f0-b1a4-4e69-4a2f-6d13471ad35b')

# Internet Sales Cube
data_model:DataModel = project.select_data_model()

df_dimensionality = data_model.get_data(['category', 'department', 'item', 'state', 'store', 'total_sales', 
                                      'total_units_sold', 'population_variance_sales', 'average_sales', 
                                      'sample_standard_deviation_sales', 'max_sales', 'average_units_sold', 
                                      'sample_standard_deviation_units_sold', 'population_variance_units_sold', 
                                      'max_units_sold', 'sample_variance_units_sold'])
df_dimensionality.tail()
"""