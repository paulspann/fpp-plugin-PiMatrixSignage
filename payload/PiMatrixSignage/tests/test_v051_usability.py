import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT))
from database import Database, SCHEMA_VERSION


class V051UsabilityTests(unittest.TestCase):
    def test_schema_and_message_history_restore(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(Path(td)/'db.sqlite3')
            self.assertGreaterEqual(SCHEMA_VERSION,9)
            msgs=db.list_messages(); self.assertTrue(msgs)
            mid=int(msgs[0]['id'])
            baseline=db.list_message_versions(mid)
            self.assertTrue(baseline)
            m=db.get_message(mid); original=m['text']
            payload=dict(m); payload['text']='VERSION TWO'; payload.pop('id',None); payload.pop('created_at',None); payload.pop('updated_at',None)
            db.save_message(payload,mid); db.save_message_version(mid,'Tester')
            versions=db.list_message_versions(mid)
            self.assertGreaterEqual(len(versions),2)
            # Pressing Save again with no content change must not create a duplicate revision.
            db.save_message_version(mid,'Tester')
            self.assertEqual(len(db.list_message_versions(mid)),len(versions))
            oldest=versions[-1]
            restored=db.restore_message_version(mid,int(oldest['id']),'Tester')
            self.assertEqual(restored['text'],original)
            self.assertGreater(len(db.list_message_versions(mid)),len(versions))

    def test_portable_import_export_ui_and_api_present(self):
        html=(ROOT/'templates'/'index.html').read_text(encoding='utf-8')
        js=(ROOT/'static'/'app.js').read_text(encoding='utf-8')
        app=(ROOT/'app.py').read_text(encoding='utf-8')
        for marker in ['exportMessage','importMessageFile','exportComponent','importComponentFile','exportPlaylist','importPlaylistFile','exportConfiguration','importConfigurationFile']:
            self.assertIn(marker,html+js)
        for marker in ['/api/portable/export/','/api/portable/import','Pi Matrix Signage Portable']:
            self.assertIn(marker,app+js)
        self.assertIn('PORTABLE_FORMAT = 1',app)

    def test_layer_clipboard_and_shortcuts(self):
        js=(ROOT/'static'/'app.js').read_text(encoding='utf-8')
        html=(ROOT/'templates'/'index.html').read_text(encoding='utf-8')
        for marker in ['pimatrixLayerClipboard','copySelectedLayers','pasteCopiedLayers','Ctrl/Cmd + C','Ctrl/Cmd + V','Ctrl/Cmd + S','Ctrl/Cmd + A','Ctrl/Cmd + G']:
            self.assertIn(marker,js+html)
        self.assertIn('shortcutModal',html)

    def test_message_history_ui_refreshes_on_navigation_save_and_restore(self):
        js=(ROOT/'static'/'app.js').read_text(encoding='utf-8')
        self.assertIn("messageHistoryPanel').addEventListener('toggle'",js)
        self.assertIn("state.messageVersions=[];renderMessageVersions();resetHistory()",js)
        self.assertIn("if($('messageHistoryPanel')?.open)await loadMessageVersions()",js)
        self.assertIn("await loadMessageVersions();toast(`Restored Version",js)
        self.assertIn("Loading saved versions",js)
        self.assertIn("if(+$('messageId').value!==id)return",js)

    def test_p5_simulation_modes(self):
        html=(ROOT/'templates'/'index.html').read_text(encoding='utf-8')
        js=(ROOT/'static'/'app.js').read_text(encoding='utf-8')
        css=(ROOT/'static'/'app.css').read_text(encoding='utf-8')
        self.assertIn('livePreviewMode',html)
        self.assertIn('designerPreviewMode',html)
        self.assertIn('applyPreviewSimulation',js)
        self.assertIn('preview-p5',css)
        self.assertIn('radial-gradient(circle at center',css)


if __name__=='__main__': unittest.main()
