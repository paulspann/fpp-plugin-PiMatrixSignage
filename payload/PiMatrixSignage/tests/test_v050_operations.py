import json, sys, tempfile, time, unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from database import Database, SCHEMA_VERSION
from renderer import RendererEngine

class OperationalV050Tests(unittest.TestCase):
    def make_db(self,td): return Database(str(Path(td)/'data'/'signage.db'))

    def test_schema_conditional_brightness_and_emergency_setting(self):
        with tempfile.TemporaryDirectory() as td:
            db=self.make_db(td)
            self.assertGreaterEqual(SCHEMA_VERSION,8)
            mids=db.list_message_options(); mid=mids[0]['id']
            rid=db.save_conditional_rule({'name':'Cold','target_type':'message','target_id':mid,'condition_type':'weather_temp','operator':'lt','compare_value':'5','config':{'lat':53.5,'lon':-2.5},'priority':200,'true_for_seconds':3,'minimum_hold_seconds':30,'enabled':True})
            r=db.get_conditional_rule(rid);self.assertEqual(r['config']['lat'],53.5);self.assertEqual(r['priority'],200)
            bid=db.save_brightness_schedule({'name':'Night','days':'0,1,2,3,4,5,6','start_time':'22:00','end_time':'06:00','brightness':15,'priority':100,'enabled':True})
            self.assertEqual(db.get_brightness_schedule(bid)['brightness'],15)
            db.update_settings({'emergency_message_id':mid});self.assertEqual(db.get_settings()['emergency_message_id'],mid)

    def test_conditional_rule_and_emergency_precedence(self):
        with tempfile.TemporaryDirectory() as td:
            db=self.make_db(td);mid=db.list_message_options()[0]['id']
            rid=db.save_conditional_rule({'name':'Windy','target_type':'message','target_id':mid,'condition_type':'weather_wind','operator':'gt','compare_value':'10','config':{},'priority':250,'enabled':True,'minimum_hold_seconds':0})
            eng=RendererEngine(db,str(Path(td)/'data'),str(Path(td)/'uploads'))
            with patch('renderer._condition_value',return_value=(20,'20mph')):
                eng._automation_cache_at=0
                target=eng._resolve_target(datetime(2026,8,17,12,0))
            self.assertEqual(target.source,f'condition:{rid}')
            db.update_settings({'emergency_message_id':mid});eng.reload_settings();eng.activate_emergency()
            target2=eng._resolve_target(datetime(2026,8,17,12,0));self.assertEqual(target2.source,'emergency')
            eng.clear_emergency()

    def test_brightness_schedule_and_remote_override(self):
        with tempfile.TemporaryDirectory() as td:
            db=self.make_db(td);db.update_settings({'brightness':60})
            db.save_brightness_schedule({'name':'Night','days':'0,1,2,3,4,5,6','start_time':'22:00','end_time':'06:00','brightness':15,'priority':100,'enabled':True})
            eng=RendererEngine(db,str(Path(td)/'data'),str(Path(td)/'uploads'))
            val,src=eng._effective_brightness(datetime(2026,8,17,23,0),time.monotonic());self.assertEqual(val,15);self.assertIn('Night',src)
            eng.set_brightness_override(75);val,src=eng._effective_brightness(datetime(2026,8,17,23,0),time.monotonic());self.assertEqual((val,src),(75,'remote override'))
            eng.set_brightness_override(None);eng._brightness_cache_at=0;val,_=eng._effective_brightness(datetime(2026,8,17,12,0),time.monotonic());self.assertEqual(val,60)

    def test_operational_ui_and_mobile_remote_are_packaged(self):
        html=(ROOT/'templates'/'index.html').read_text();js=(ROOT/'static'/'app.js').read_text();remote=(ROOT/'templates'/'remote.html').read_text();app=(ROOT/'app.py').read_text()
        for marker in ('Conditional content','Brightness schedules','Emergency / priority','id="activateEmergency"','id="emergencyMessageSetting"'):
            self.assertIn(marker,html)
        for marker in ('/api/conditional-rules','/api/brightness-schedules','/api/emergency/activate','/api/brightness/override','/api/show/blank'):
            self.assertIn(marker,app+js+remote)
        self.assertIn('Pi Matrix Remote',remote);self.assertIn('ACTIVATE EMERGENCY',remote)

if __name__=='__main__': unittest.main(verbosity=2)
