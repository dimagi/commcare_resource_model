# Cluster Model

This tool is used for modeling the resources (CPU, RAM, Storage) required
to run a system. The model is quite generic but is designed with CommCare HQ
in mind.

# Usage

    # create a virtual env
    $ python3 -m venv /path/to/new/virtual/environment

    # install requirements
    $ pip install -U pip
    $ pip install -r requirements.txt

    # run tool
    $ python run_model.py -h
    $ python run_model.py /path/to/config.yml

# Model overview
This tool works on the following model:

* Define the expected usage of the system for each month.
* Define the services in use by the system including storage and processing
requirements per unit 'usage' item.

The model will then apply the usage values to the services models
to obtain the CPU, RAM, Storage and number of VMs required to run the service
over the months defined in the model.

# Configuration
The tool takes a config file which defines the parameters of the model
for the system.

The config file is split into 4 sections:

## Global config

| Key                  | Description |
| -------------------- | ----------- |
| etimation_buffer     | Factor to inflate values by to account for estimation difference |
| estimation_growth_factor | Rate at which the estimation buffer grows (per month) |
| storage_buffer       | Factor to inflate storage values by to ensure disks to get to 100% capacity. |
| storage_display_unit | GB or TB |
| vm_os_storage_gb     | GB storage per VM for OS etc |
| vm_os_storage_group  | Group name for OS storage |
| summary_dates        | List of dates to generate summaries at. Date format: YYYY-MM |
| usage                | See [Usage Config](#usage-config) section below |
| service              | See [Service Config](#service-config) section below |


## Usage config
This sections describes the usage of the system e.g. number of users, volume of transactions etc.

This section may have any number of named items in it to describe different
aspects of the system. Each item may be a standalone item or reference
other items.

Each item in this section defines which 'model' it will use to simulate the usage.
The available models are as follows:

### Date range value
This model assigns a specific number to each date range in a list. If a range is only for a single month the end date can be omitted.

Example:
The follow example defined the number of users of the system
in fro 2017-11 to 2019-12.

    users:
        model: 'date_range_value'
        ranges:
          - ['20171101', 5000]
          - ['20171201', 10000]
          - ['20180101', '20181201', 100000]
          - ['20190101', '20191201', 200000]


### Derived Factor
Multiply another field by a fixed factor.

Example:
10 forms per user per month

    forms:
        model: 'derived_factor'
        start_with: 91000000  # initial value. Defaults to 0.
        dependant_field: 'users'  # Value is derived from this field
        factor: 10  # Factor to multiply the dependant field by

### Derived Sum
Sum multiple other fields

Example:
Total kafka changes

    kafka_changes:
        model: 'derived_sum'
        dependant_fields: ['forms', 'cases', 'case_transactions']

### Cumulative
This model performs a cumulative sum of the values.

Example:
Total forms ever created.

    forms_total:
        model: 'cumulative'
        dependant_field: 'forms'

### Cumulative with limited lifespan
Similar to 'Cumulative' this performs a cumulative sum of the dependant field
but only over the most recent N months.

Example:
Logs that get deleted after 2 months

    device_logs_total:
        model: 'cumulative_limited_lifespan'
        dependant_field: 'device_logs'
        lifespan: 2

## Baseline with monthly growth
This is a combination model that simplifies modelling fields that have an initial
amount and then grow over time at a constant rate.

Example.
Cases modeled as 600 per user initially with 50 new cases being added per month:

    cases_total:
        model: 'baseline_with_growth'
        dependant_field: 'users'
        baseline: 600
        monthly_growth: 50
        start_with: 2000000  # account for existing data

This model also outputs the monthly and baseline fields for use in other calculations formatted as follows:

* {name}_baseline
* {name}_monthly

## Service config
Each item in the service config defines a service which the system uses.
The services are related to the usage values to calculate required resources.

| Param name                | Description |
| ------------------------- | ----------- |
| usage_capacity_per_node   | The capacity that a single node can handle |
| usage_field               | (optional) Field to reference for usage. Default to 'users' |
| min_nodes                 | (optional) Minimum number of nodes (VMs). Defaults to '1' |
| storage_scales_with_nodes | (optional) True if each new node contains a complete copy of the data e.g. SQL replica |
| max_storage_per_node      | (optional) Set the maximum amount of storage each node should have.  Node count will be adjusted accordingly. |
| storage                   | (optional) Define service storage. Exclude this section for processing only services. |
| process                   | (optional) Define the processing requirements. Exclude this section for storage only services e.g S3 |

### Storage
For storage services the storage section should be included.

    storage:
      group: 'SSD'  # name of the storage group
      redundancy_factor: 1  # Use a value of more than 1 for services that store data redundantly
      static_baseline: 0  # Bytes to include as a static value to account for overhead etc.
      data_models:  # List of data models
        - referenced_field: 'forms_total'
          unit_size: 1200
        - referenced_field: 'cases_total'
          unit_size: 2K
        - referenced_field: 'case_transactions_total'
          unit_size: 515
          
#### Fixed sized disks
For some services we want a fixed disk size regardless of the usage e.g. Django.
To accomplish this we can define the storage as follows:

    service:
      storage:
        group: 'VM_other'
        static_baseline: 50GB
        override_storage_buffer: 0  # don't add storage buffer
        override_estimation_buffer: 0  # don't apply estimation buffer

### Process
For services that require compute resources (CPU / RAM) the 'process' section should be defined.

This section has three modes:

#### Fixed number of VMs
e.g. airflow / control

    airflow:
      static_number: 2
      process:
        cores_per_node: 4
        ram_per_node: 8

#### Single process
e.g. Django worker

    usage_capacity_per_node: 1000
    process:
      cores_per_node: 4
      ram_per_node: 6

#### Multi-process
e.g. Celery task queues

In this case the `usage_capacity_per_node` field is not required since
the capacity is defined for each sub-process.

    process:
      cores_per_node: 8
      ram_per_node: 16
      cores_per_sub_process: 1
      ram_per_sub_process: 0.5
      sub_processes:
        - name: 'queue1'
          static_number: 30  # regardless of the usage there will always be 30
        - name: 'queue2'
          capacity: 20000  # 1 per 20000 users
          
#### RAM scales with usage
e.g. Riak keys or Redis

For processes that store data in memory you can define
the model for how much RAM is required. This will have the effect
of adding VMs to the total count if extra are required to make up
the total RAM requirement.

    process:
        cores_per_node: 8
        ram_per_node: 32
        ram_model:
            - referenced_field: 'forms_total'
              unit_size: 86
            - referenced_field: 'images_total'
              unit_size: 86
        ram_redundancy_factor: 3
        ram_static_baseline: 1  # GB per node

# Determining parameters for the config
Writing the config files is relatively easy but the hard part is getting the numbers correct
so that you can get realistic results.

This sections outlines a few techniques for doing that.

## Usage
The usage data will vary significantly from system to system (or project to project)
based on the design.

For CommCare HQ there are some internal tools
that help to determine system usage:

    python manage.py project_stats_report <domain>


## Storage

**static_baseline**
This should be the disc usage that the system is currently using as indicated by tools
like `du`.

**unit_bytes**
Depending on how the data is stored this can be determined in a number of ways:

_SQL_
For SQL you want to total storage size per row including indexes etc.
This query (and others like it) are useful for determining that:
https://dba.stackexchange.com/questions/23879/measure-the-size-of-a-postgresql-table-row

_Elasticsearch_
For Elasticsearch you inspect the index metadata to get doc counts and
disc usage from which you can drive average size per doc. This assumes
you need an average for all docs.

If you need a size for specific doc types you should take a representative
sample of those docs and average their size.

_RiakCS_
There's no good way to get this info directly from Riak but if you
have the metadata stored elsewhere you can query that e.g. SQL attachments table.

_CouchDB_
Use a similar approach to Elasticsearch.

## Process
To determine RAM and CPU requirements for processes you can inspect process
metrics to determine their RAM and CPU usage.

The best way to do this is to use a tool like Datadog to track usage
over time and then inspect the data to find reasonable values.

CPU usage is a little harder than RAM but the approach is similar, you
should observe the CPU usage over time for a known load or use load testing
to determine CPU usage requirements.

_RiakCS_
RAM: this depends on the backend that's in use. For Bitcask you need enough
memory to store all the keys in RAM. Note: ICDS uses Bitcask

http://docs.basho.com/riak/kv/2.2.3/setup/planning/bitcask-capacity-calc/

| Variable | Description |
|----------|-------------|
| Static Bitcask per-key overhead | 44.5 bytes per key |
| Estimated average bucket-plus-key length | The combined number of characters your bucket + keynames will require (on average). We’ll assume 1 byte per character. |
| Estimated total objects | The total number of key/value pairs your cluster will have when started |
| Replication Value (n_val) | The number of times each key will be replicated when written to Riak (the default is 3) |


Approximate RAM Needed for Bitcask = (static bitcask per key overhead + estimated average bucket+key length in bytes) * estimate total number of keys * n_val

# Analysis Model

This server sensitivity analysis tool is used to analyze the effects of different fields (from the cluster config
 file) on server sizing. The purpose of this is to determine how, for example, increasing the number of forms
 submitted per month would affect the server requirements of the system.

# Usage

    # create virtual env and install requirements as described in the Cluster Model Usage section
    
    # run tool:
    $ python run_analysis.py <path to cluster config file> -a <path to analysis file> -o <output xlsx filename>

# Model overview
This tool runs the [Cluster Model](#cluster-model) described above with different weights applied to specified fields in the cluster
config file, and then compares the outputs. The values that are compared in the output are: RAM (GB), 
CPU (Total Cores), SAS Storage (TB), SSD Storage (TB) and Total VMs. This shows the effect of a particular field
on server requirements.

# Analysis Configuration
This tool takes in two config files. One defines the parameters of the model
for the system (which is the same as described in [Configuration](#configuration)). The other defines the 
parameters of the analysis. Here is an example config:

```
forms_monthly:
  factor_start: .5
  factor_end: 1.5
  factor_step: .5
  field_name: factor
```

| Key                  | Description |
| -------------------- | ----------- |
| forms_monthly        | This key, which in the example is `forms_monthly` is the name of the parameter being analyzed. |
| factor_start         | This is the starting number in the multiplication factor list. |
| factor_end           | This is the ending number in the multiplication factor list. |
| factor_step		   | The step size of the multiplication factor list.|
| field_name    	   | This is the name of the field (within the parameter) that is being varied. |



