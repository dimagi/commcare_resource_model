from unittest import TestCase
import os
from io import StringIO
import pandas as pd
from pandas.util.testing import assert_frame_equal

from core.generate import ComputeModel, generate_usage_data, _service_storage_data, generate_service_data
from core.config import config_from_path, ServiceDef, ProcessDef, SubProcessDef, StorageSizeDef, StorageDef


class UsageModelTests(TestCase):
    def setUp(self):
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                   'configs', 'test-usage-config.yml')
        self.config = config_from_path(config_file)
        self.usage_data = generate_usage_data(self.config)
        self.service_name = 'test_service'
        self.service_def = ServiceDef()

    def test_generate_service_data(self):
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                   'configs', 'test-usage-and-service-config.yml')
        config = config_from_path(config_file)
        usage_data = generate_usage_data(config)
        service_data = generate_service_data(config, usage_data)
        expected = """,pg_proxy,pg_proxy,pg_proxy,pg_proxy,pg_proxy,pg_proxy
                    ,Users,computed_data_frame,computed_data_frame,computed_data_frame,computed_data_frame,Data Storage
                    ,users,CPU,RAM,VMs,VMs Usage,storage
                    2017-06-01,1000000,40.0,160.0,10.0,10.0,2325000000000.0
                    2017-07-01,1000000,40.0,160.0,10.0,10.0,2325000000000.0
                    2017-08-01,1000000,40.0,160.0,10.0,10.0,2325000000000.0
                """
        assert_frame_equal(service_data, self._from_csv(expected))

    def test_data_frame(self):
        self._add_processes_and_subprocesses()
        self._add_storage()
        usage, compute_model = self._get_user_data()
        computed_data_frame = compute_model.data_frame(self.usage_data, self._get_data_storage())
        expected = """,CPU,RAM,VMs,VMs Usage,Additional VMs (storage),Additional VMs (RAM),RAM requirement
            2017-06-01,8.0,8.0,2.0,1.0,1.0,0.0,0.001
            2017-07-01,8.0,8.0,3.0,1.0,2.0,0.0,0.002
            2017-08-01,8.0,8.0,4.0,1.0,3.0,0.0,0.003
        """
        assert_frame_equal(computed_data_frame, self._from_csv(expected))

    def test_calculate_sub_process_resources_single_process(self):
        self._add_processes_and_subprocesses()
        usage, compute_model = self._get_user_data()
        computed_data_frame = compute_model._calculate_sub_process_resources(usage)


        expected = """,CPU,RAM,VMs
            2017-06-01,8.0,8.0,1.0
            2017-07-01,8.0,8.0,1.0
            2017-08-01,8.0,8.0,1.0
                """
        assert_frame_equal(computed_data_frame, self._from_csv(expected))

    def test_calculate_usage_capacity_per_node(self):
        self._add_processes_and_subprocesses()
        usage, compute_model = self._get_user_data()
        computed_data_frame = compute_model._calculate_usage_capacity_per_node(usage)
        expected = """,CPU,RAM,VMs
            2017-06-01,32.0,128.0,2.0
            2017-07-01,64.0,256.0,4.0
            2017-08-01,96.0,384.0,6.0
        """
        assert_frame_equal(computed_data_frame, self._from_csv(expected))

    def test_calculate_max_storage_per_node_bytes(self):
        self._add_processes_and_subprocesses()
        usage, compute_model = self._get_user_data()
        computed_data_frame = compute_model._calculate_usage_capacity_per_node(usage)
        computed_data_frame = compute_model._calculate_max_storage_per_node_bytes(computed_data_frame, self._get_data_storage())
        expected = """,CPU,RAM,VMs,Additional VMs (storage)
            2017-06-01,32.0,128.0,2.0,0.0
            2017-07-01,64.0,256.0,4.0,0.0
            2017-08-01,96.0,384.0,6.0,0.0
            """
        assert_frame_equal(computed_data_frame, self._from_csv(expected))

    def test_calculate_ram_model(self):
        self._add_processes_and_subprocesses()
        self._add_storage()
        usage, compute_model = self._get_user_data()
        computed_data_frame = compute_model._calculate_usage_capacity_per_node(usage)
        computed_data_frame = compute_model._calculate_ram_model(self.usage_data, computed_data_frame)
        expected = """,CPU,RAM,VMs,Additional VMs (RAM),RAM requirement
            2017-06-01,32.0,128.0,2.0,0.0,0.001
            2017-07-01,64.0,256.0,4.0,0.0,0.002
            2017-08-01,96.0,384.0,6.0,0.0,0.003
            """
        assert_frame_equal(computed_data_frame, self._from_csv(expected))

    def test_service_storage_data(self):
        self._add_storage()
        data_storage = _service_storage_data(self.config, self.service_def, self.usage_data)
        expected = """,storage
            2017-06-01,1100000.0
            2017-07-01,2200000.0
            2017-08-01,3300000.0
            """
        assert_frame_equal(data_storage, self._from_csv(expected))

    def _from_csv(self, expected):
        return pd.read_csv(StringIO(expected), index_col=0, parse_dates=True)

    def _add_processes_and_subprocesses(self, cores_per_node=16, ram_per_node=64, ram_static_baseline=0,
                                        ram_redundancy_factor=1, cores_per_sub_process=1,
                                        ram_per_sub_process=1, subprocess_static_number=8,
                                        usage_capacity_per_node=500000, max_storage_per_node=1099900):
        service_def_process = ProcessDef({})

        service_def_process._allow_dynamic_properties = False
        service_def_process.cores_per_node = cores_per_node
        service_def_process.ram_per_node = ram_per_node
        service_def_process.ram_static_baseline = ram_static_baseline
        service_def_process.ram_redundancy_factor = ram_redundancy_factor
        service_def_process.cores_per_sub_process = cores_per_sub_process
        service_def_process.ram_per_sub_process = ram_per_sub_process
        self.service_def.usage_capacity_per_node = usage_capacity_per_node
        self.service_def.max_storage_per_node = max_storage_per_node

        # Define the subprocess
        subprocess = SubProcessDef({})
        subprocess.name = "pillowtop"
        subprocess.static_number = subprocess_static_number

        service_def_process.sub_processes = [subprocess]

        self.service_def.process = service_def_process

    def _add_storage(self, ram_unit_size=1):
        self.service_def.storage = StorageDef()
        storage_data_model = StorageSizeDef({"referenced_field": "users",
                                             "unit_size": "{}".format(ram_unit_size)})
        self.service_def.storage.data_models = [storage_data_model]



        ram_model = StorageSizeDef({"_allow_dynamic_properties": "False",
                                    "referenced_field": "users",
                                    "unit_size": "{}".format(ram_unit_size)})

        self.service_def.process.ram_model = [ram_model]

    def _get_user_data(self):
        compute_model = ComputeModel(self.service_name, self.service_def)
        usage = self.usage_data[self.service_def.usage_field]

        return usage, compute_model

    def _get_data_storage(self):
        data_storage = _service_storage_data(self.config, self.service_def, self.usage_data)
        return data_storage
