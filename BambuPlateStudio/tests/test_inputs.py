import math
import unittest
from BambuPlateStudio.core.inputs import color_hex,config_change,placement_change
from BambuPlateStudio.core.model import DEFAULT_CONFIG


class EditorInputsTests(unittest.TestCase):
    def test_config_change_is_atomic(self):
        original=dict(DEFAULT_CONFIG)
        with self.assertRaises(ValueError):config_change(original,{'gap':12,'margin':float('nan')})
        self.assertEqual(original,DEFAULT_CONFIG)

    def test_config_rejects_nonfinite_negative_and_bool_numbers(self):
        for value in [float('nan'),float('inf'),-1,True]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                config_change(DEFAULT_CONFIG,{'gap':value})

    def test_config_rejects_unknown_options_and_bad_types(self):
        for values in [{'unknown':1},{'enableSupport':'false'},{'refinement':'extreme'},{'nozzle':0}]:
            with self.subTest(values=values),self.assertRaises(ValueError):config_change(DEFAULT_CONFIG,values)

    def test_nozzle_normalization(self):
        self.assertEqual(config_change(DEFAULT_CONFIG,{'nozzle':'0.40'})['nozzle'],'0.4')

    def test_placement_requires_existing_integer_plate(self):
        base={'plate':1,'x':10,'y':20,'angle':90}
        for plate in [0,1.5,3,float('nan'),True]:
            with self.subTest(plate=plate),self.assertRaises(ValueError):
                placement_change(dict(base,plate=plate),{1,2})
        self.assertEqual(placement_change(base,{1,2}),(1,10.,20.,90.))

    def test_placement_cannot_introduce_nan_or_infinity(self):
        for key in ['x','y','angle']:
            for value in [float('nan'),float('inf')]:
                data={'plate':1,'x':10,'y':20,'angle':0};data[key]=value
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):placement_change(data,{1})

    def test_colors_normalized_and_strict(self):
        self.assertEqual(color_hex(' #e7e1e1 '),'#E7E1E1')
        for value in ['red','#abcd','#1234567',None,'#zzzzzz']:
            with self.subTest(value=value),self.assertRaises(ValueError):color_hex(value)
