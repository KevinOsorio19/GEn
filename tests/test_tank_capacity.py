import unittest
from backend.engine import calculate
from backend.services import validate_tank_limit

class TankCapacityTests(unittest.TestCase):
 def test_limit_includes_initial_fill_without_changing_consumption(self):
  tanks=[dict(id=1,date='2026-03-01',odometer=100,gallons=6),dict(id=2,date='2026-03-10',odometer=200,gallons=5)]
  base=dict(energy_group='M1',slope=.05,intercept=0,target=.05,max_tank_gallons=5)
  r=calculate(tanks,baseline=base)
  self.assertEqual(r['gallons'],5);self.assertEqual(r['theoretical'],5)
  self.assertEqual(r['quality'],'REQUIERE REVISIÓN')
  self.assertEqual([a['transaction_id'] for a in r['tank_capacity_alerts']],[1])
  self.assertIn('2026-03-01',r['notes'][-1]);self.assertIn('M1',r['notes'][-1])
 def test_single_fill_and_missing_interval_still_alert(self):
  r=calculate([dict(id=2,date='2026-03-01',odometer=100,gallons=5.1)],baseline={'max_tank_gallons':5})
  self.assertEqual(len(r['tank_capacity_alerts']),1);self.assertIsNone(r['gallons'])
 def test_equal_or_unconfigured_does_not_alert(self):
  tanks=[dict(date='2026-03-01',odometer=100,gallons=5)]
  for base in [None,{},dict(max_tank_gallons=5)]:self.assertEqual(calculate(tanks,baseline=base)['tank_capacity_alerts'],[])
 def test_invalid_limits(self):
  for value in [0,-5,'no','nan','inf']:
   with self.assertRaises(ValueError):validate_tank_limit(value)
  for value in [None,'',5,'5']:validate_tank_limit(value)
