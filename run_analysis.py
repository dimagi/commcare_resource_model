import argparse
import subprocess
from collections import namedtuple

import copy
import json
import pandas as pd
import tempfile

from core.config import cluster_config_from_path, dict_config_from_path
from core.generate import generate_usage_data, generate_service_data
from core.summarize import summarize_service_data, get_summary_data
from core.writers import ExcelWriter

SummaryData = namedtuple('SummaryData', 'storage compute')


def get_git_revision_hash():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf8')

def generate_server_configs(server_config, analysis_config):
    configs_to_analyze = []
    for analysis_field in analysis_config:
        for usage_field in server_config["usage"]:
            if usage_field == analysis_field:
                model_params = generate_model_params(server_config["usage"][usage_field], analysis_config[analysis_field], usage_field)
                # Generate a different cluster config for each entry in model_params
                for model_param in model_params:
                    analysis_model_dict = copy.deepcopy(server_config)
                    analysis_model_dict["usage"][usage_field] = model_param['model']
                    # Write the config to a temp file so it can be make into a ClusterConfig object
                    with open(tempfile.NamedTemporaryFile().name, 'a+') as f:
                        f.write(json.dumps(analysis_model_dict))
                        f.seek(0)
                        analysis_model_config = cluster_config_from_path(f.name)
                    configs_to_analyze.append({"model": analysis_model_config,
                                               "field_to_modify": model_param["field_to_modify"],
                                               "subfield_to_modify": model_param["subfield_to_modify"],
                                               "step_value": model_param["step_value"]})

    return configs_to_analyze


def generate_model_params(model_params, analysis_config_entry, field_to_modify):
    step_values = generate_steps(analysis_config_entry)
    analysis_model_params = []
    subfield_to_modify = analysis_config_entry["field_name"]
    for step_value in step_values:
        this_model_def = copy.deepcopy(model_params)
        this_model_def[subfield_to_modify] = step_value * model_params[subfield_to_modify]
        analysis_model_params.append({"model": this_model_def,
                                      "field_to_modify": field_to_modify,
                                      "subfield_to_modify": subfield_to_modify,
                                      "step_value": step_value})
    return analysis_model_params

def generate_steps(analysis_config_entry):
    val_to_add = analysis_config_entry["factor_start"]
    step_values = []
    while val_to_add <= analysis_config_entry["factor_end"]:
        step_values.append(val_to_add)
        val_to_add += analysis_config_entry["factor_step"]
    return step_values

def compare_to_baseline_values(field_to_update, output_data, baseline_step_value_index):
    return ['{}%'.format(value/(output_data[field_to_update][baseline_step_value_index]) * 100) for value in output_data[field_to_update]]

if __name__ == '__main__':

    parser = argparse.ArgumentParser('CommCare Cluster Model')
    parser.add_argument('server_config', help='Path to cluster config file')
    parser.add_argument('-a', '--analysis_config', help='Path to analysis config file', required=True)
    parser.add_argument('-o', '--output', help='Write output to Excel file at this path.', required=True)
    parser.add_argument('-s', '--service', help='Only output data for specific service.')

    args = parser.parse_args()

    pd.options.display.float_format = '{:.1f}'.format

    analysis_config = dict_config_from_path(args.analysis_config)

    # Get the server config as a dict
    base_server_config = dict_config_from_path(args.server_config)
    # Make a list of ClusterConfig objects with all the different modifications specified in the analysis_config file
    all_server_config_data = generate_server_configs(base_server_config, analysis_config)

    # Create the dictionary, which will eventually be written to excel
    output_data = {'Field to Modify': [],
                   'Subfield to Modify': [],
                   'Step Value': [],
                   'RAM (GB)': [],
                   'CPU (Total Cores)': [],
                   'SAS Storage (TB)': [],
                   'SSD Storage (TB)': [],
                   'Total VMs': [],}

    # Generate server and usage data for each ClusterConfig object
    for server_config_data in all_server_config_data:
        server_config = server_config_data['model']
        usage = generate_usage_data(server_config)
        service_data = generate_service_data(server_config, usage)
        summary_data = get_summary_data(server_config, service_data)

        if server_config.summary_dates:
            summary_dates = server_config.summary_date_vals
        else:
            summary_dates = [usage.iloc[-1].name]  # summarize at final date


        date_list = list(usage.index.to_series())

        summary = summarize_service_data(server_config, summary_data, summary_dates[0])
        user_count = usage.loc[summary_dates[0]]['users']

        # Append the dictionary entries with the calculated value for each ClusterConfig object
        output_data['Field to Modify'].append(server_config_data['field_to_modify'])
        output_data['Subfield to Modify'].append(server_config_data['subfield_to_modify'])
        output_data['Step Value'].append(server_config_data['step_value'])

        output_data['RAM (GB)'].append(summary[0].iloc[0]['RAM Total (GB)'])
        output_data['CPU (Total Cores)'].append(summary[0].iloc[0]['Cores Total'])
        output_data['SAS Storage (TB)'].append(summary[1].iloc[0]['Rounded Total (TB)'])
        output_data['SSD Storage (TB)'].append(summary[1].iloc[1]['Rounded Total (TB)'])
        output_data['Total VMs'].append(summary[0].iloc[0]['VMs Total'])

    # Add dictionary entries which compare the values to the baseline value and display percentages
    baseline_step_value_index = [index for index, value in enumerate(output_data["Step Value"]) if value==1][0]

    # Compare outputs in output_data to the baseline values
    output_data['RAM (% change from baseline)'] = compare_to_baseline_values('RAM (GB)', output_data, baseline_step_value_index)
    output_data['CPU (% change from baseline)'] = compare_to_baseline_values('CPU (Total Cores)', output_data, baseline_step_value_index)
    output_data['SAS Storage (% change from baseline)'] = compare_to_baseline_values('SAS Storage (TB)', output_data, baseline_step_value_index)
    output_data['SSD Storage (% change from baseline)'] = compare_to_baseline_values('SSD Storage (TB)', output_data, baseline_step_value_index)
    output_data['Total VMs (% change from baseline)'] = compare_to_baseline_values('Total VMs', output_data, baseline_step_value_index)
    output_data['Step Value (% change from baseline)'] = ['{}%'.format(val * 100) for val in output_data['Step Value']]

    # Convert the dictionary to a DataFrame and write to an excel spreadsheet
    output_dataframe = pd.DataFrame(data=output_data, index=output_data['Field to Modify'])
    writer = ExcelWriter(args.output)
    with writer:
        writer.write_data_frame(
            data_frame=output_dataframe,
            sheet_name='Server Sizing Analysis',
            header='Server config: {}, Analysis Config: {}'.format(args.server_config, args.analysis_config),
            index_label='Field getting modified'
        )
