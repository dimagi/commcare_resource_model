from io import StringIO
from unittest import TestCase

import pandas as pd
from pandas.util.testing import assert_frame_equal

from core.models import CumulativeModel, LimitedLifetimeModel, DerivedSum, \
    DerivedFactor, DateValueModel


class UsageModelTests(TestCase):
    def test_date_range_value(self):
        result = _get_user_data()
        expected = """,users
            2017-01-01,100
            2017-02-01,100
            2017-03-01,200
            2017-04-01,200
        """
        assert_frame_equal(result, self._from_csv(expected))

    def test_date_value(self):
        m = DateValueModel('test', [
            ['20180101', 10],
            ['20180201', 20],
            ['20180301', 30],
        ])
        frame = m.data_frame(None)
        expected = """,test
            2018-01-01,10
            2018-02-01,20
            2018-03-01,30
        """
        assert_frame_equal(frame, self._from_csv(expected))

    def _from_csv(self, expected):
        return pd.read_csv(StringIO(expected), index_col=0, parse_dates=True)

    def test_can_run(self):
        model = DerivedFactor('forms', dependant_field='users', factor=1)
        self.assertFalse(model.can_run(pd.DataFrame()))
        self.assertTrue(model.can_run(_get_user_data()))

    def test_cumulative(self):
        user_data = _get_user_data()
        result = CumulativeModel('total', dependant_field='users').data_frame(user_data)
        expected = """,total
            2017-01-01,100
            2017-02-01,200
            2017-03-01,400
            2017-04-01,600
        """
        assert_frame_equal(result, self._from_csv(expected))

    def test_cumulative_limited_lifespan(self):
        user_data = _get_user_data()
        result = LimitedLifetimeModel('total_live', dependant_field='users', lifespan=2).data_frame(user_data)
        expected = """,total_live
            2017-01-01,100
            2017-02-01,200
            2017-03-01,300
            2017-04-01,400
        """
        assert_frame_equal(result, self._from_csv(expected))

    def test_derived_sum(self):
        user_data = _get_user_data()
        forms = DerivedFactor('forms', 'users', 5).data_frame(user_data)
        user_forms = pd.concat([user_data, forms], axis=1)
        result = DerivedSum('sum', dependant_fields=['users', 'forms']).data_frame(user_forms)
        expected = """,sum
            2017-01-01,600
            2017-02-01,600
            2017-03-01,1200
            2017-04-01,1200
        """
        assert_frame_equal(result, self._from_csv(expected))

    def test_derived_factor(self):
        user_data = _get_user_data()
        result = DerivedFactor('2x', dependant_field='users', factor=2).data_frame(user_data)
        expected = """,2x
            2017-01-01,200
            2017-02-01,200
            2017-03-01,400
            2017-04-01,400
        """
        assert_frame_equal(result, self._from_csv(expected))


def _get_user_data():
    model = DateValueModel('users', [
        ['20170101', '20170201', 100],
        ['20170301', '20170401', 200],
    ])
    return model.data_frame(pd.DataFrame())
